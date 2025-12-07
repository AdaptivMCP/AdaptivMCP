"""Workspace and command tools for GitHub MCP."""

import os
import shlex
import sys
from typing import Any, Dict, List, Optional

from github_mcp.config import RUN_COMMAND_MAX_CHARS
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import _ensure_write_allowed, _structured_tool_error, mcp_tool
from github_mcp.utils import _effective_ref_for_repo
from github_mcp.workspace import (
    _apply_patch_to_repo,
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
    _workspace_path,
)

# ------------------------------------------------------------------------------
# Workspace / full-environment tools
# ------------------------------------------------------------------------------


def _workspace_deps() -> Dict[str, Any]:
    main_module = sys.modules.get("main")
    return {
        "clone_repo": getattr(main_module, "_clone_repo", _clone_repo),
        "run_shell": getattr(main_module, "_run_shell", _run_shell),
        "prepare_temp_virtualenv": getattr(
            main_module, "_prepare_temp_virtualenv", _prepare_temp_virtualenv
        ),
        "apply_patch_to_repo": getattr(
            main_module, "_apply_patch_to_repo", _apply_patch_to_repo
        ),
        "ensure_write_allowed": getattr(
            main_module, "_ensure_write_allowed", _ensure_write_allowed
        ),
    }


@mcp_tool(write_action=True)
async def ensure_workspace_clone(
    full_name: str, ref: str = "main", reset: bool = False
) -> Dict[str, Any]:
    """Ensure a persistent workspace exists for ``full_name``/``ref``.

    When ``reset`` is True, the workspace is refreshed to match the remote
    branch, discarding local edits. Otherwise, the existing workspace (if any)
    is kept intact so commands and commits share the same on-disk tree.
    """

    try:
        effective_ref = _effective_ref_for_repo(full_name, ref)
        workspace_dir = _workspace_path(full_name, effective_ref)
        existed = os.path.isdir(os.path.join(workspace_dir, ".git"))

        deps = _workspace_deps()
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=not reset
        )

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "reset": reset,
            "created": not existed,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="ensure_workspace_clone")


@mcp_tool(write_action=False)
async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Run an arbitrary shell command in a persistent workspace clone.

    Args:
        full_name: GitHub repository in ``owner/name`` format.
        ref: Branch, tag, or commit to check out. Defaults to ``main``.
        command: Shell command to execute inside the clone.
        timeout_seconds: Hard timeout applied to the command execution.
        workdir: Optional path inside the repository to use as the working
            directory.
        patch: Optional unified diff that will be applied before running the
            command so assistants can run tests against in-flight edits.
        use_temp_venv: When true (default), commands run inside a temporary
            virtualenv rooted in the workspace so ``pip install`` steps do not
            mutate the server-wide environment. The virtualenv is reused across
            calls when the workspace persists on disk.
        installing_dependencies: Set to ``true`` when the command installs
            packages or otherwise mutates the server environment so write
            gating can apply to that call. Commands that only inspect or
            modify the workspace can leave this false for faster iteration.
        mutating: Set to ``true`` when the command is expected to edit files
            in the workspace so the write gate can apply only to those
            calls. Read-only and test commands can leave this false so they
            run without requiring write approval.

    The workspace directory is kept on disk so subsequent calls can reuse
    installed dependencies and edits. The same workspace is shared with
    ``commit_workspace`` so changes made via ``run_command`` remain available
    for commits and later commands. Callers should pass a patch when they need
    the workspace to mirror in-flight edits. The tool is read-tagged by default;
    set ``mutating=true`` (or the other gating flags) when a command will write
    so approval applies only to those cases.
    """

    env: Optional[Dict[str, str]] = None
    try:
        deps = _workspace_deps()
        effective_ref = _effective_ref_for_repo(full_name, ref)
        if len(command) > RUN_COMMAND_MAX_CHARS:
            raise ValueError(
                f"run_command.command is too long ({len(command)} chars); "
                "use diff-based tools (apply_text_update_and_commit, "
                "apply_patch_and_commit, update_file_sections_and_commit) "
                "for large edits instead of embedding scripts in command."
            )
        needs_write_gate = mutating or installing_dependencies or not use_temp_venv
        if needs_write_gate:
            deps["ensure_write_allowed"](
                f"run_command {command} in {full_name}@{effective_ref}"
            )
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        if patch:
            await deps["apply_patch_to_repo"](repo_dir, patch)

        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await deps["run_shell"](
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        return {
            "repo_dir": repo_dir,
            "workdir": workdir,
            "result": result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="run_command")


@mcp_tool(write_action=True)
async def commit_workspace(
    full_name: str,
    ref: str = "main",
    message: str = "Commit workspace changes",
    add_all: bool = True,
    push: bool = True,
) -> Dict[str, Any]:
    """Commit and optionally push changes from the persistent workspace.

    Args:
        full_name: GitHub repository in ``owner/name`` format.
        ref: Branch to commit to. Defaults to ``main`` but will map to the
            controller default branch when appropriate.
        message: Commit message used when writing changes.
        add_all: Stage all changes with ``git add -A`` before committing.
        push: Whether to push the commit back to the remote branch.
    """

    try:
        effective_ref = _effective_ref_for_repo(full_name, ref)
        _ensure_write_allowed(
            f"commit_workspace for {full_name}@{effective_ref}",
            target_ref=effective_ref,
        )
        deps = _workspace_deps()
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        if add_all:
            add_result = await deps["run_shell"](
                "git add -A", cwd=repo_dir, timeout_seconds=120
            )
            if add_result["exit_code"] != 0:
                stderr = add_result.get("stderr", "") or add_result.get(
                    "stdout", ""
                )
                raise GitHubAPIError(f"git add failed: {stderr}")

        status_result = await deps["run_shell"](
            "git status --porcelain", cwd=repo_dir, timeout_seconds=60
        )
        status_lines = status_result.get("stdout", "").strip().splitlines()
        if not status_lines:
            raise GitHubAPIError("No changes to commit in workspace")

        commit_cmd = f"git commit -m {shlex.quote(message)}"
        commit_result = await deps["run_shell"](
            commit_cmd, cwd=repo_dir, timeout_seconds=300
        )
        if commit_result["exit_code"] != 0:
            stderr = commit_result.get("stderr", "") or commit_result.get(
                "stdout", ""
            )
            raise GitHubAPIError(f"git commit failed: {stderr}")

        push_result = None
        if push:
            push_cmd = f"git push origin HEAD:{effective_ref}"
            push_result = await deps["run_shell"](
                push_cmd, cwd=repo_dir, timeout_seconds=300
            )
            if push_result["exit_code"] != 0:
                stderr = push_result.get("stderr", "") or push_result.get(
                    "stdout", ""
                )
                raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "status": status_lines,
            "commit": commit_result,
            "push": push_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_workspace")


@mcp_tool(write_action=True)
async def commit_workspace_files(
    full_name: str,
    files: List[str],
    ref: str = "main",
    message: str = "Commit selected workspace changes",
    push: bool = True,
) -> Dict[str, Any]:
    """Commit and optionally push specific files from the persistent workspace."""

    if not files:
        raise ValueError("files must be a non-empty list of paths")

    try:
        effective_ref = _effective_ref_for_repo(full_name, ref)
        _ensure_write_allowed(
            f"commit_workspace_files for {full_name}@{effective_ref}",
            target_ref=effective_ref,
        )
        deps = _workspace_deps()
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        add_cmd = "git add -- " + " ".join(shlex.quote(path) for path in files)
        add_result = await deps["run_shell"](
            add_cmd, cwd=repo_dir, timeout_seconds=120
        )
        if add_result["exit_code"] != 0:
            stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
            raise GitHubAPIError(f"git add failed: {stderr}")

        staged_files_result = await deps["run_shell"](
            "git diff --cached --name-only", cwd=repo_dir, timeout_seconds=60
        )
        staged_files = staged_files_result.get("stdout", "").strip().splitlines()
        if not staged_files:
            raise GitHubAPIError("No staged changes to commit for provided files")

        commit_cmd = f"git commit -m {shlex.quote(message)}"
        commit_result = await deps["run_shell"](
            commit_cmd, cwd=repo_dir, timeout_seconds=300
        )
        if commit_result["exit_code"] != 0:
            stderr = commit_result.get("stderr", "") or commit_result.get(
                "stdout", ""
            )
            raise GitHubAPIError(f"git commit failed: {stderr}")

        push_result = None
        if push:
            push_cmd = f"git push origin HEAD:{effective_ref}"
            push_result = await deps["run_shell"](
                push_cmd, cwd=repo_dir, timeout_seconds=300
            )
            if push_result["exit_code"] != 0:
                stderr = push_result.get("stderr", "") or push_result.get(
                    "stdout", ""
                )
                raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "staged_files": staged_files,
            "commit": commit_result,
            "push": push_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_workspace_files")


@mcp_tool(write_action=False)
async def get_workspace_changes_summary(
    full_name: str,
    ref: str = "main",
    path_prefix: Optional[str] = None,
    max_files: int = 200,
) -> Dict[str, Any]:
    """Summarize the current workspace changes for a repo/ref.

    This helper inspects the persistent workspace for ``full_name``/``ref``
    and returns a structured view of modified, added, deleted, renamed, and
    untracked files. It is intended as a light-weight "what did I change?"
    helper that assistants can call before committing or opening a PR.
    """

    deps = _workspace_deps()
    effective_ref = _effective_ref_for_repo(full_name, ref)
    repo_dir = await deps["clone_repo"](
        full_name, ref=effective_ref, preserve_changes=True
    )

    status_result = await deps["run_shell"](
        "git status --porcelain=v1", cwd=repo_dir, timeout_seconds=60
    )
    raw_status = status_result.get("stdout", "")
    lines = [line for line in raw_status.splitlines() if line.strip()]

    def _within_prefix(path: str) -> bool:
        if not path_prefix:
            return True
        prefix = path_prefix.rstrip("/")
        return path == prefix or path.startswith(prefix + "/")

    changes: List[Dict[str, Any]] = []
    summary = {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "renamed": 0,
        "untracked": 0,
    }

    for line in lines:
        if len(line) < 3:
            continue
        x = line[0]
        y = line[1]
        rest = line[3:]

        if " -> " in rest:
            src, dst = rest.split(" -> ", 1)
            path = dst
            change_type = "R"
        else:
            src = rest
            dst = None
            path = src
            change_type = "??" if x == "?" and y == "?" else "M"

        if not _within_prefix(path):
            continue

        if x == "?" and y == "?":
            summary["untracked"] += 1
        elif x == "A" or y == "A":
            change_type = "A"
            summary["added"] += 1
        elif x == "D" or y == "D":
            change_type = "D"
            summary["deleted"] += 1
        elif x == "R" or y == "R":
            change_type = "R"
            summary["renamed"] += 1
        else:
            change_type = "M"
            summary["modified"] += 1

        if len(changes) < max_files:
            changes.append({
                "status": change_type,
                "path": path,
                "src": src,
                "dst": dst,
            })

    has_changes = any(summary.values())
    return {
        "ref": effective_ref,
        "has_changes": has_changes,
        "summary": summary,
        "changes": changes,
    }



@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Run the project's test command inside the persistent workspace.

    ``run_tests`` is a thin wrapper around ``run_command`` with a more explicit
    default timeout. Provide ``patch`` when running tests against pending edits
    so the checkout matches the assistant's current working diff.
    Set ``installing_dependencies`` to ``true`` only when the test command also
    installs packages so gating can apply to that narrower use case. Set
    ``mutating=true`` only when the tests will rewrite files; read-only test
    runs remain ungated by default.

    The returned object always includes a top-level "status" field summarizing
    the outcome ("passed" or "failed") and echoes the test command so callers
    and smoke tests can reason about the run without digging into the raw
    command result.
    """
    result = await run_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    # If run_command surfaced a structured error (for example an auth or clone
    # failure), treat that as a failed test run but keep the error payload.
    if isinstance(result, dict) and "error" in result:
        return {
            "status": "failed",
            "command": test_command,
            "error": result["error"],
        }

    # Normal shape: run_command returned repo/workdir plus a nested result
    # object containing the exit code and streams.
    if not isinstance(result, dict) or "result" not in result:
        return {
            "status": "failed",
            "command": test_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "run_command returned an unexpected result structure",
                "raw_result": result,
            },
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"

    return {
        "status": status,
        "command": test_command,
        "exit_code": exit_code,
        "repo_dir": result.get("repo_dir"),
        "workdir": result.get("workdir"),
        "result": cmd_result,
    }

@mcp_tool(write_action=False)
async def run_quality_suite(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Run the standard quality suite for a repo/branch.

    Today this is a thin wrapper around ``run_tests`` so controllers can
    standardize on a single "quality gate" tool. Future versions may extend
    this helper to run linters or formatters alongside tests.
    """
    return await run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "ruff check .",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Run the lint/static-analysis suite for a repo/branch.

    By default this runs ``ruff check .`` inside the workspace for the given
    repo/ref. Callers can override ``lint_command`` to run different or
    additional tools (for example ``mypy`` or project-specific scripts).

    This helper is parallel to ``run_quality_suite`` but focused on style and
    static analysis rather than tests.
    """
    return await run_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

@mcp_tool(write_action=False)
async def build_pr_summary(
    full_name: str,
    ref: str,
    title: str,
    body: str,
    changed_files: Optional[List[str]] = None,
    tests_status: Optional[str] = None,
    lint_status: Optional[str] = None,
    breaking_changes: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build a structured summary for a pull request description.

    This helper does **not** call the GitHub API. Instead, it returns a
    normalized JSON object that controllers can render into a rich,
    high-level PR description or use for automated quality checks.

    Controllers should treat this as the canonical schema for AI-authored
    PR descriptions in this repo.
    """
    return {
        "repo": full_name,
        "ref": ref,
        "title": title,
        "body": body,
        "changed_files": changed_files or [],
        "tests_status": tests_status or "unknown",
        "lint_status": lint_status or "unknown",
        "breaking_changes": bool(breaking_changes) if breaking_changes is not None else None,
    }

# Split from github_mcp.tools_workspace (generated).
import asyncio
import os
import shlex
import uuid
from typing import Any

from github_mcp import config
from github_mcp.command_classification import infer_write_action_from_shell
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)
from github_mcp.utils import _normalize_timeout_seconds

from ._shared import (
    _cmd_invokes_git,
    _maybe_install_dev_requirements,
    _tw,
)


_TEST_ARTIFACT_DIRS = {
    ".pytest_cache",
    "htmlcov",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage-html",
}

_TEST_ARTIFACT_FILES = {
    ".coverage",
    "coverage.xml",
    "junit.xml",
    "pytest.xml",
    "pytest-report.xml",
}


def _looks_like_pytest_command(command: str, command_lines: list[str] | None) -> bool:
    """Heuristically detect pytest invocations.

    We use a conservative substring match because many callers embed pytest
    inside compound shell commands (e.g. "python -m pytest", "coverage run -m pytest",
    "pytest -q && echo done").
    """

    blob = "\n".join(command_lines or []) if command_lines else (command or "")
    s = blob.lower()
    return ("pytest" in s) or ("-m pytest" in s)


def _augment_env_for_pytest(env: dict[str, str] | None) -> dict[str, str] | None:
    """Reduce test artifact churn for pytest runs.

    - PYTHONDONTWRITEBYTECODE=1 avoids __pycache__ / *.pyc creation.
    - Disabling pytest's cache provider prevents `.pytest_cache/`.

    The changes are best-effort and only applied when the caller is running
    pytest. We avoid heavy-handed settings like PYTEST_DISABLE_PLUGIN_AUTOLOAD
    which can break repos that rely on plugins.
    """

    out = dict(env or {})
    out.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    addopts = str(out.get("PYTEST_ADDOPTS") or "")
    if "no:cacheprovider" not in addopts:
        out["PYTEST_ADDOPTS"] = (addopts + " -p no:cacheprovider").strip()
    return out


def _cleanup_test_artifacts(repo_dir: str) -> dict[str, Any]:
    """Best-effort removal of common test artifacts under a repo root.

    This is intentionally conservative:
    - Only removes well-known transient paths.
    - Never recurses into `.git/` or `.venv-mcp/`.
    """

    repo_real = os.path.realpath(repo_dir)
    removed_dirs = 0
    removed_files = 0
    errors: list[str] = []

    # Fast-path: remove known top-level artifacts.
    for d in sorted(_TEST_ARTIFACT_DIRS):
        p = os.path.join(repo_real, d)
        if os.path.isdir(p):
            try:
                for root, dirs, files in os.walk(p, topdown=False):
                    for fn in files:
                        try:
                            os.remove(os.path.join(root, fn))
                        except Exception as exc:
                            errors.append(
                                f"remove_file:{os.path.relpath(os.path.join(root, fn), repo_real)}:{exc}"
                            )
                    for dn in dirs:
                        try:
                            os.rmdir(os.path.join(root, dn))
                        except Exception:
                            # Directory may not be empty; continue best-effort.
                            pass
                os.rmdir(p)
                removed_dirs += 1
            except Exception as exc:
                errors.append(f"remove_dir:{d}:{exc}")

    for f in sorted(_TEST_ARTIFACT_FILES):
        p = os.path.join(repo_real, f)
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed_files += 1
            except Exception as exc:
                errors.append(f"remove_file:{f}:{exc}")

    # Sweep: remove __pycache__ dirs and *.pyc/*.pyo files (excluding venv/git).
    skip_dirs = {".git", ".venv-mcp"}
    for root, dirs, files in os.walk(repo_real, topdown=True):
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        # Remove stray bytecode files.
        for fn in list(files):
            if fn.endswith(".pyc") or fn.endswith(".pyo"):
                try:
                    os.remove(os.path.join(root, fn))
                    removed_files += 1
                except Exception as exc:
                    errors.append(
                        f"remove_file:{os.path.relpath(os.path.join(root, fn), repo_real)}:{exc}"
                    )

        # Remove __pycache__ directories encountered in this level.
        if "__pycache__" in dirs:
            pyc_dir = os.path.join(root, "__pycache__")
            try:
                for r2, d2, f2 in os.walk(pyc_dir, topdown=False):
                    for fn in f2:
                        try:
                            os.remove(os.path.join(r2, fn))
                        except Exception as exc:
                            errors.append(
                                f"remove_file:{os.path.relpath(os.path.join(r2, fn), repo_real)}:{exc}"
                            )
                    for dn in d2:
                        try:
                            os.rmdir(os.path.join(r2, dn))
                        except Exception:
                            pass
                os.rmdir(pyc_dir)
                removed_dirs += 1
            except Exception as exc:
                errors.append(f"remove_dir:{os.path.relpath(pyc_dir, repo_real)}:{exc}")
            try:
                dirs.remove("__pycache__")
            except ValueError:
                pass

    return {
        "removed_dir_count": removed_dirs,
        "removed_file_count": removed_files,
        "errors": errors[:25],
        "error_count": len(errors),
    }


def _terminal_command_write_action(args: dict[str, Any]) -> bool:
    """Infer the write/read classification for terminal_command invocations."""

    command = str(args.get("command") or "")
    command_lines = args.get("command_lines")
    lines = command_lines if isinstance(command_lines, list) else None
    installing = bool(args.get("installing_dependencies", False))
    return infer_write_action_from_shell(
        command, command_lines=lines, installing_dependencies=installing
    )


def _always_write(_args: dict[str, Any]) -> bool:
    """Resolver for tools that are inherently write actions."""

    return True


def _normalize_command_payload(
    command: str,
    command_lines: list[str] | None,
) -> tuple[str, list[str]]:
    """Normalize command inputs.

    Returns:
    - requested_command: the raw intended command (may contain newlines)
    - command_lines_out: list of command lines (never contains newlines)
    """

    # Prefer permissive coercion over raising on common client mistakes.
    requested = (
        command
        if isinstance(command, str)
        else (str(command) if command is not None else "")
    )
    if command_lines is not None:
        # Accept strings, list/tuples, or any iterable. Coerce each element to str.
        if isinstance(command_lines, str):
            raw_lines: list[str] = command_lines.splitlines()
        elif isinstance(command_lines, (list, tuple)):
            raw_lines = [
                line if isinstance(line, str) else str(line) for line in command_lines
            ]
        else:
            try:
                raw_lines = [str(line) for line in list(command_lines)]  # type: ignore[arg-type]
            except Exception:
                raw_lines = []

        # Ensure the output list never contains embedded newlines.
        lines_out: list[str] = []
        for line in raw_lines:
            split = (line or "").splitlines()
            lines_out.extend(split if split else [""])
        requested = "\n".join(lines_out)
    else:
        lines_out = requested.splitlines() if requested else []

    return requested, lines_out


def _resolve_workdir(repo_dir: str, workdir: str | None) -> str:
    """Resolve a working directory inside the repo mirror.

    For consistency across tools, ``workdir`` is expected to be repository-relative.
    However, some callers pass the absolute `workdir` returned by prior tool
    invocations back into subsequent calls. To make this round-trip safe,
    absolute paths are accepted when they resolve inside the repo mirror.
    """

    repo_real = os.path.realpath(repo_dir)
    if not workdir:
        return repo_real
    if not isinstance(workdir, str):
        try:
            workdir = str(workdir)
        except Exception:
            return repo_real

    normalized = workdir.strip().replace("\\", "/")
    if not normalized or normalized in {".", "./", "/"}:
        return repo_real

    # Accept absolute paths that point inside the repo mirror.
    if os.path.isabs(normalized) or normalized.startswith("/"):
        candidate_abs = os.path.realpath(normalized)
        if candidate_abs == repo_real or candidate_abs.startswith(repo_real + os.sep):
            if not os.path.isdir(candidate_abs):
                return repo_real
            return candidate_abs

        # Common caller intent: "/subdir" means repo-relative "subdir".
        normalized = normalized.lstrip("/")
        if not normalized:
            return repo_real

    # Reject parent-directory traversal rather than clamping.
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("workdir must not contain '..' segments")
        parts.append(part)
    normalized = "/".join(parts)
    if not normalized:
        return repo_real

    candidate = os.path.realpath(os.path.join(repo_real, normalized))
    if candidate != repo_real and not candidate.startswith(repo_real + os.sep):
        raise ValueError("workdir must resolve inside the workspace repository")
    if not os.path.isdir(candidate):
        return repo_real
    return candidate


@mcp_tool(write_action=True)
async def render_shell(
    full_name: str,
    *,
    command: str = "echo hello Render",
    command_lines: list[str] | None = None,
    create_branch: str | None = None,
    push_new_branch: bool = True,
    ref: str = "main",
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Render-focused shell entry point for interacting with GitHub workspaces.

    This helper mirrors the Render deployment model by operating through the
    server-side repo mirror. It ensures the repo mirror exists
    for the default branch (or a provided ref), optionally creates a fresh
    branch from that ref, and then executes the supplied shell command inside
    the repo mirror.
    """

    timeout_seconds = _normalize_timeout_seconds(
        timeout_seconds, config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS
    )

    try:
        requested_command, command_lines_out = _normalize_command_payload(
            command,
            command_lines,
        )

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        branch_creation: dict[str, Any] | None = None
        target_ref = effective_ref

        if create_branch:
            branch_creation = await _tw().workspace_create_branch(
                full_name=full_name,
                base_ref=effective_ref,
                new_branch=create_branch,
                push=push_new_branch,
            )

            if push_new_branch:
                # Remote branch exists, safe to target it directly.
                target_ref = create_branch
            else:
                # Note: branch exists only locally in the base repo mirror.
                # Do NOT try to clone a non-existent remote branch.
                target_ref = effective_ref
                command = f"git checkout {shlex.quote(create_branch)} && {command}"

        command_result = await _tw().terminal_command(
            full_name=full_name,
            ref=target_ref,
            command=command,
            timeout_seconds=timeout_seconds,
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
        )

        cleaned_command = command_result

        # logic can report exit code/stdout/stderr for render_shell as well.
        out: dict[str, Any] = {
            "full_name": full_name,
            "base_ref": effective_ref,
            "target_ref": target_ref,
            "branch": branch_creation,
            "status": cleaned_command.get("status")
            if isinstance(cleaned_command, dict)
            else None,
            "ok": cleaned_command.get("ok")
            if isinstance(cleaned_command, dict)
            else None,
            "error": cleaned_command.get("error")
            if isinstance(cleaned_command, dict)
            else None,
            "error_detail": cleaned_command.get("error_detail")
            if isinstance(cleaned_command, dict)
            else None,
            "workdir": (
                cleaned_command.get("workdir")
                if isinstance(cleaned_command, dict)
                else None
            ),
            # Keep payload fields newline-free to avoid downstream double-escaping.
            "command_input": command,
            "command_lines": command_lines_out,
            "command": (
                cleaned_command.get("command")
                if isinstance(cleaned_command, dict)
                else command
            ),
            "install": (
                cleaned_command.get("install")
                if isinstance(cleaned_command, dict)
                else None
            ),
            "result": cleaned_command.get("result")
            if isinstance(cleaned_command, dict)
            else None,
        }
        return out
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _structured_tool_error(
            exc, context="render_shell", tool_surface="render_shell"
        )


@mcp_tool(
    write_action=True,
    write_action_resolver=_terminal_command_write_action,
    # terminal commands execute in the workspace environment.
    open_world_hint=True,
    destructive_hint=True,
    ui={
        "group": "workspace",
        "icon": "🖥️",
        "label": "Terminal Command",
        "danger": "high",
    },
)
async def terminal_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Run a shell command inside the repo mirror and return its result.

    This supports tests, linters, and project scripts that need the real working
    tree.

    Execution model:

    - The command runs within the server-side repo mirror (a persistent git
      working copy).
    - If ``use_temp_venv=true`` (default), the server ensures a **persistent**
      workspace virtualenv exists at ``<repo_dir>/.venv-mcp`` and runs the
      command inside it.
    - If ``installing_dependencies=true`` and ``use_temp_venv=true``, the tool
      will run a best-effort `pip install -r dev-requirements.txt` before
      executing the command.

    The venv lifecycle can be managed explicitly via the workspace venv tools
    (start/stop/status), but it is also safe to rely on this implicit
    preparation.

    The repo mirror persists across calls so file edits and git state are
    preserved until explicitly reset.
    """

    timeout_seconds = _normalize_timeout_seconds(
        timeout_seconds, config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS
    )

    env: dict[str, str] | None = None
    requested_command, command_lines_out = _normalize_command_payload(
        command,
        command_lines,
    )
    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        is_pytest = _looks_like_pytest_command(requested_command, command_lines_out)
        if is_pytest:
            env = _augment_env_for_pytest(env)

        cwd = _resolve_workdir(repo_dir, workdir)

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command

        install_result, install_steps = await _maybe_install_dev_requirements(
            deps,
            repo_dir=repo_dir,
            # Always install from repo root so the requirements filename resolves.
            cwd=repo_dir,
            env=env,
            timeout_seconds=timeout_seconds,
            installing_dependencies=installing_dependencies,
            use_temp_venv=use_temp_venv,
        )

        result = await deps["run_shell"](
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )

        cleanup_summary: dict[str, Any] | None = None
        if is_pytest:
            cleanup_summary = _cleanup_test_artifacts(repo_dir)

        # Best-effort: if the caller created a new local branch (e.g. via
        # `git checkout -b foo` / `git switch -c foo`) ensure the corresponding
        # branch exists on origin so subsequent tool calls that rely on
        # `origin/<branch>` do not fail.
        auto_push: dict[str, Any] | None = None
        if _cmd_invokes_git(command):
            try:
                t_default = _normalize_timeout_seconds(
                    config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS,
                    timeout_seconds,
                )
                # Only attempt when we are on a named branch (not detached).
                cur = await deps["run_shell"](
                    "git symbolic-ref --quiet --short HEAD",
                    cwd=cwd,
                    timeout_seconds=t_default,
                    env=env,
                )
                current_branch = (
                    (cur.get("stdout", "") or "").strip()
                    if isinstance(cur, dict)
                    else ""
                )
                if current_branch:
                    default_branch = _tw()._default_branch_for_repo(full_name)
                    if current_branch != default_branch:
                        # If upstream is already configured, do nothing.
                        upstream = await deps["run_shell"](
                            "git rev-parse --abbrev-ref --symbolic-full-name @{u}",
                            cwd=cwd,
                            timeout_seconds=t_default,
                            env=env,
                        )
                        has_upstream = bool(
                            isinstance(upstream, dict)
                            and upstream.get("exit_code", 0) == 0
                            and (upstream.get("stdout", "") or "").strip()
                        )
                        if not has_upstream:
                            # Check whether the branch exists on origin.
                            await deps["run_shell"](
                                "git fetch --prune origin",
                                cwd=cwd,
                                timeout_seconds=t_default,
                                env=env,
                            )
                            remote_check = await deps["run_shell"](
                                f"git ls-remote --heads origin {shlex.quote(current_branch)}",
                                cwd=cwd,
                                timeout_seconds=t_default,
                                env=env,
                            )
                            remote_exists = bool(
                                isinstance(remote_check, dict)
                                and (remote_check.get("stdout", "") or "").strip()
                            )
                            if not remote_exists:
                                push_res = await deps["run_shell"](
                                    f"git push -u origin {shlex.quote(current_branch)}",
                                    cwd=cwd,
                                    timeout_seconds=t_default,
                                    env=env,
                                )
                                auto_push = {
                                    "current_branch": current_branch,
                                    "remote_check": remote_check,
                                    "push": push_res,
                                }
            except Exception as _auto_exc:
                # Do not fail the user's command if auto-push encounters issues.
                auto_push = {"error": str(_auto_exc)}

        exit_code = 0
        timed_out = False
        if isinstance(result, dict):
            try:
                exit_code = int(result.get("exit_code", 0) or 0)
            except Exception:
                exit_code = 0
            timed_out = bool(result.get("timed_out", False))

        ok = (exit_code == 0) and (not timed_out)
        status = "ok" if ok else "failed"

        error: str | None = None
        error_detail: dict[str, Any] | None = None
        if not ok:
            error = (
                "Command timed out"
                if timed_out
                else f"Command exited with code {exit_code}"
            )
            error_detail = {"exit_code": exit_code, "timed_out": timed_out}

        out: dict[str, Any] = {
            "status": status,
            "ok": ok,
            **({"error": error, "error_detail": error_detail} if error else {}),
            "workdir": cwd,
            # Keep payload fields newline-free to avoid downstream double-escaping.
            "command_input": command,
            "command_lines": command_lines_out,
            "command": command,
            "install": install_result,
            "install_steps": install_steps,
            "result": result,
            **({"auto_push_branch": auto_push} if auto_push is not None else {}),
            **({"test_artifact_cleanup": cleanup_summary} if cleanup_summary else {}),
        }

        return out
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _structured_tool_error(
            exc, context="terminal_command", tool_surface="terminal_command"
        )


def _safe_repo_relative_path(repo_dir: str, path: str) -> str:
    """Return a repo-relative, safe path.

    Prevent absolute paths and path traversal outside the repo mirror.
    """

    # Be permissive: coerce common non-string inputs instead of raising.
    if not isinstance(path, str):
        try:
            path = str(path)
        except Exception:
            path = ""

    normalized = (path or "").strip().replace("\\", "/")
    if not normalized:
        return ".mcp_tmp/invalid_path"
    repo_real = os.path.realpath(repo_dir)

    # Accept absolute paths as long as they resolve inside the repo mirror.
    if os.path.isabs(normalized) or normalized.startswith("/"):
        candidate = os.path.realpath(normalized)
        if candidate != repo_real and candidate.startswith(repo_real + os.sep):
            rel = os.path.relpath(candidate, repo_real).replace("\\", "/")
            if rel and rel not in {".", "./"}:
                return rel
            return ".mcp_tmp/invalid_path"

        # Common caller intent: "/foo/bar" means repo-relative "foo/bar".
        normalized = normalized.lstrip("/")
        if not normalized:
            return ".mcp_tmp/invalid_path"

    # Reject parent-directory traversal rather than clamping.
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path must not contain '..' segments")
        parts.append(part)
    normalized = "/".join(parts)
    if not normalized:
        return ".mcp_tmp/invalid_path"

    candidate = os.path.realpath(os.path.join(repo_real, normalized))
    repo_real = os.path.realpath(repo_dir)
    if candidate == repo_real or not candidate.startswith(repo_real + os.sep):
        return ".mcp_tmp/invalid_path"
    return normalized


@mcp_tool(
    write_action=True,
    write_action_resolver=_always_write,
    open_world_hint=True,
    ui={
        "group": "workspace",
        "icon": "🐍",
        "label": "Run Python",
        "danger": "medium",
    },
)
async def run_python(
    full_name: str,
    ref: str = "main",
    script: str = "",
    filename: str | None = None,
    args: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Run an inline Python script inside the repo mirror.

    The script content is written to a file within the workspace mirror and executed.
    The tool exists to support multi-line scripts without relying on shell-special syntax.
    """

    timeout_seconds = _normalize_timeout_seconds(
        timeout_seconds, config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS
    )

    # Be permissive with tool inputs: coerce and let downstream execution handle failures.
    if not isinstance(script, str):
        try:
            script = str(script)
        except Exception:
            script = ""

    if args is not None:
        if isinstance(args, str):
            args = [args]
        elif isinstance(args, (list, tuple)):
            args = [a if isinstance(a, str) else str(a) for a in args]
        else:
            try:
                args = [str(a) for a in list(args)]  # type: ignore[arg-type]
            except Exception:
                args = None

    env: dict[str, str] | None = None
    created_temp_file = False
    created_rel_path: str | None = None

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = _resolve_workdir(repo_dir, workdir)

        rel_path = (
            filename.strip() if isinstance(filename, str) and filename.strip() else None
        )
        if rel_path is None:
            rel_path = f".mcp_tmp/run_python_{uuid.uuid4().hex}.py"

        created_temp_file = filename is None or not (
            isinstance(filename, str) and filename.strip()
        )
        created_rel_path = rel_path

        rel_path = _safe_repo_relative_path(repo_dir, rel_path)
        abs_path = os.path.realpath(os.path.join(repo_dir, rel_path))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(script)

        install_result, install_steps = await _maybe_install_dev_requirements(
            deps,
            repo_dir=repo_dir,
            # Always install from repo root so the requirements filename resolves.
            cwd=repo_dir,
            env=env,
            timeout_seconds=timeout_seconds,
            installing_dependencies=installing_dependencies,
            use_temp_venv=use_temp_venv,
        )

        cmd = "python " + shlex.quote(rel_path)
        if args:
            cmd += " " + " ".join(shlex.quote(a) for a in args)

        result = await deps["run_shell"](
            cmd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )

        return {
            "workdir": cwd,
            "ref": effective_ref,
            "script_path": rel_path,
            "command": cmd,
            "install": install_result,
            "install_steps": install_steps,
            "result": result,
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _structured_tool_error(
            exc, context="run_python", tool_surface="run_python"
        )
    finally:
        if cleanup:
            try:
                deps = _tw()._workspace_deps()
                effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
                repo_dir = await deps["clone_repo"](
                    full_name, ref=effective_ref, preserve_changes=True
                )
                if created_temp_file and created_rel_path:
                    rel_path2 = _safe_repo_relative_path(repo_dir, created_rel_path)
                    abs_path2 = os.path.realpath(os.path.join(repo_dir, rel_path2))
                    if os.path.isfile(abs_path2):
                        os.remove(abs_path2)
            except Exception:
                # Best-effort cleanup.
                pass


# NOTE: The legacy tool name `run_command` has been removed.
# `terminal_command` replaces it.
#
# However, several downstream clients (and prompt templates) still call
# `run_command`, `run_shell`, `terminal_commands`, or `run_terminal_commands`.
# To avoid breaking those callers, we keep lightweight MCP-tool aliases that
# forward to `terminal_command`.


# NOTE: These aliases must preserve the same write/read classification behavior
# as `terminal_command`. Otherwise, read-only calls (e.g., `pytest`) would be
# incorrectly gated as write actions when invoked via legacy tool names.
@mcp_tool(
    write_action=True,
    name="run_command",
    write_action_resolver=_terminal_command_write_action,
    # Match the behavioral/safety hints from `terminal_command`.
    open_world_hint=True,
    destructive_hint=True,
)
async def run_command_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`terminal_command`.

    This exists for older MCP clients that still invoke `run_command`.
    """

    payload = await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        command_lines=command_lines,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )
    if isinstance(payload, dict):
        if payload.get("command_input") == payload.get("command"):
            payload.pop("command_input", None)
        if command_lines is None:
            payload.pop("command_lines", None)
    return payload


@mcp_tool(
    write_action=True,
    name="run_shell",
    write_action_resolver=_terminal_command_write_action,
    open_world_hint=True,
    destructive_hint=True,
)
async def run_shell_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`terminal_command`.

    Some integrations refer to the workspace command runner as `run_shell`.
    """

    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        command_lines=command_lines,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


@mcp_tool(
    write_action=True,
    name="terminal_commands",
    write_action_resolver=_terminal_command_write_action,
    open_world_hint=True,
    destructive_hint=True,
)
async def terminal_commands_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`terminal_command`.

    Some older tool catalogs refer to the terminal runner as `terminal_commands`.
    """

    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        command_lines=command_lines,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


@mcp_tool(
    write_action=True,
    name="run_terminal_commands",
    write_action_resolver=_terminal_command_write_action,
    open_world_hint=True,
    destructive_hint=True,
)
async def run_terminal_commands_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: list[str] | None = None,
    timeout_seconds: float = 0,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for :func:`terminal_command`.

    This name appears in some older controller-side tool catalogs.
    """

    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        command_lines=command_lines,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )

# Split from github_mcp.tools_workspace (generated).
import asyncio
import os
import shlex
import uuid
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)
from github_mcp.command_classification import infer_write_action_from_shell
from github_mcp.utils import _normalize_timeout_seconds

from ._shared import _tw


def _terminal_command_write_action(args: Dict[str, Any]) -> bool:
    """Infer the write/read classification for terminal_command invocations."""

    command = str(args.get("command") or "")
    command_lines = args.get("command_lines")
    lines = command_lines if isinstance(command_lines, list) else None
    installing = bool(args.get("installing_dependencies", False))
    return infer_write_action_from_shell(command, command_lines=lines, installing_dependencies=installing)


def _always_write(_args: Dict[str, Any]) -> bool:
    """Resolver for tools that are inherently write actions."""

    return True


def _normalize_command_payload(
    command: str,
    command_lines: Optional[list[str]],
) -> tuple[str, list[str]]:
    """Normalize command inputs.

    Returns:
    - requested_command: the raw intended command (may contain newlines)
    - command_lines_out: list of command lines (never contains newlines)
    """

    requested = command
    if command_lines is not None:
        if not isinstance(command_lines, list) or any(
            (not isinstance(line, str)) for line in command_lines
        ):
            raise ValueError("command_lines must be a list[str]")
        requested = chr(10).join(command_lines)
        lines_out = list(command_lines)
    else:
        lines_out = requested.splitlines() if requested else []

    return requested, lines_out
def _resolve_workdir(repo_dir: str, workdir: Optional[str]) -> str:
    """Resolve a working directory inside the repo mirror.

    For consistency across tools, ``workdir`` must be repository-relative.
    Absolute paths are rejected.
    """

    repo_real = os.path.realpath(repo_dir)
    if not workdir:
        return repo_real
    if not isinstance(workdir, str):
        raise ValueError("workdir must be a string")

    normalized = workdir.strip().replace("\\", "/")
    if not normalized or normalized in {".", "./"}:
        return repo_real
    if os.path.isabs(normalized) or normalized.startswith("/"):
        raise ValueError("workdir must be repository-relative (no leading '/')")

    candidate = os.path.realpath(os.path.join(repo_real, normalized))
    if candidate != repo_real and not candidate.startswith(repo_real + os.sep):
        raise ValueError("workdir must resolve inside the workspace repository")
    if not os.path.isdir(candidate):
        raise ValueError("workdir must point to a directory")
    return candidate


def _extract_missing_module(stdout: str, stderr: str) -> str:
    """Best-effort extraction of a missing module name from Python tracebacks."""
    combined = f"{stderr}\n{stdout}" if (stdout or stderr) else ""
    # Common patterns:
    # - "ModuleNotFoundError: No module named 'ruff'"
    # - "No module named ruff" (some runtimes omit the exception type)
    markers = [
        "ModuleNotFoundError: No module named ",
        "No module named ",
    ]
    pos = -1
    marker = ""
    for m in markers:
        p = combined.find(m)
        if p != -1:
            pos = p
            marker = m
            break
    if pos == -1:
        return ""
    tail = combined[pos + len(marker) :].strip()
    if not tail:
        return ""
    if tail[:1] in ('"', "'"):
        q = tail[0]
        rest = tail[1:]
        endq = rest.find(q)
        return (rest[:endq] if endq != -1 else rest).strip()
    return (tail.split()[0] if tail else "").strip()


def _required_packages_for_command(command: str) -> list[str]:
    """Best-effort mapping from a shell command to pip-installable packages.

    This is intentionally conservative: it only covers common dev tools.
    """

    if not command:
        return []

    c = command.strip()
    lower = c.lower()

    # Common Python quality tools.
    if lower.startswith("ruff ") or lower == "ruff" or "python -m ruff" in lower:
        return ["ruff"]
    if lower.startswith("mypy ") or lower == "mypy" or "python -m mypy" in lower:
        return ["mypy"]
    if (
        lower.startswith("pytest")
        or "python -m pytest" in lower
        or lower.startswith("python -m pytest")
    ):
        return ["pytest"]
    if lower.startswith("black ") or lower == "black":
        return ["black"]
    if lower.startswith("isort ") or lower == "isort":
        return ["isort"]
    if lower.startswith("flake8 ") or lower == "flake8":
        return ["flake8"]
    if lower.startswith("bandit ") or lower == "bandit":
        return ["bandit"]
    if lower.startswith("pip-audit") or "pip-audit" in lower:
        return ["pip-audit"]

    return []


@mcp_tool(write_action=True)
async def render_shell(
    full_name: str,
    *,
    command: str = "echo hello Render",
    command_lines: Optional[list[str]] = None,
    create_branch: Optional[str] = None,
    push_new_branch: bool = True,
    ref: str = "main",
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
    """Render-focused shell entry point for interacting with GitHub workspaces.

    This helper mirrors the Render deployment model by operating through the
    server-side repo mirror. It ensures the repo mirror exists
    for the default branch (or a provided ref), optionally creates a fresh
    branch from that ref, and then executes the supplied shell command inside
    the repo mirror.
    """

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)

    try:
        requested_command, command_lines_out = _normalize_command_payload(
            command,
            command_lines,
        )

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        branch_creation: Optional[Dict[str, Any]] = None
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
        out: Dict[str, Any] = {
            "full_name": full_name,
            "base_ref": effective_ref,
            "target_ref": target_ref,
            "branch": branch_creation,
            "status": cleaned_command.get("status") if isinstance(cleaned_command, dict) else None,
            "ok": cleaned_command.get("ok") if isinstance(cleaned_command, dict) else None,
            "error": cleaned_command.get("error") if isinstance(cleaned_command, dict) else None,
            "error_detail": cleaned_command.get("error_detail")
            if isinstance(cleaned_command, dict)
            else None,
            "workdir": (
                cleaned_command.get("workdir") if isinstance(cleaned_command, dict) else None
            ),
            # Keep payload fields newline-free to avoid downstream double-escaping.
            "command_input": command,
            "command_lines": command_lines_out,
            "command": (
                cleaned_command.get("command") if isinstance(cleaned_command, dict) else command
            ),
            "install": (
                cleaned_command.get("install") if isinstance(cleaned_command, dict) else None
            ),
            "result": cleaned_command.get("result") if isinstance(cleaned_command, dict) else None,
        }
        return out
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _structured_tool_error(exc, context="render_shell", tool_surface="render_shell")


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
    command_lines: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
    """Run a shell command inside the repo mirror and return its result.

    This supports tests, linters, and project scripts that need the real working
    tree.

    Execution model:

    - The command runs within the server-side repo mirror (a persistent git
      working copy).
    - If ``use_temp_venv=true`` (default), the server creates an ephemeral
      virtualenv for the duration of the command.
    - If ``installing_dependencies=true`` and ``use_temp_venv=true``, the tool
      will run a best-effort `pip install -r dev-requirements.txt` before
      executing the command.

    The repo mirror persists across calls so file edits and git state are
    preserved until explicitly reset.
    """

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)

    env: Optional[Dict[str, str]] = None
    requested_command, command_lines_out = _normalize_command_payload(
        command,
        command_lines,
    )
    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = _resolve_workdir(repo_dir, workdir)

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command

        install_result = None
        install_steps: list[Dict[str, Any]] = []
        if installing_dependencies and use_temp_venv:
            install_cmd = "python -m pip install -r dev-requirements.txt"
            install_result = await deps["run_shell"](
                install_cmd,
                cwd=cwd,
                timeout_seconds=max(600, timeout_seconds),
                env=env,
            )
            install_steps.append({"command": install_cmd, "result": install_result})
            if isinstance(install_result, dict) and install_result.get("exit_code", 0) != 0:
                i_stderr = install_result.get("stderr") or ""
                i_stdout = install_result.get("stdout") or ""
                raise GitHubAPIError(
                    "Dependency installation failed: " + (i_stderr.strip() or i_stdout.strip())
                )

        result = await deps["run_shell"](
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )

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

        error: Optional[str] = None
        error_detail: Optional[Dict[str, Any]] = None
        if not ok:
            error = "Command timed out" if timed_out else f"Command exited with code {exit_code}"
            error_detail = {"exit_code": exit_code, "timed_out": timed_out}

        out: Dict[str, Any] = {
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

    if not isinstance(path, str):
        raise ValueError("path must be a string")
    normalized = path.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("path must be non-empty")
    if normalized.startswith("/"):
        raise ValueError("path must be repo-relative")
    candidate = os.path.realpath(os.path.join(repo_dir, normalized))
    repo_real = os.path.realpath(repo_dir)
    if candidate == repo_real or not candidate.startswith(repo_real + os.sep):
        raise ValueError("path must resolve inside the repo mirror")
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
    filename: Optional[str] = None,
    args: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    cleanup: bool = True,
) -> Dict[str, Any]:
    """Run an inline Python script inside the repo mirror.

    The script content is written to a file within the workspace mirror and executed.
    The tool exists to support multi-line scripts without relying on shell-special syntax.
    """

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)

    if not isinstance(script, str) or not script.strip():
        raise ValueError("script must be a non-empty string")

    if args is not None:
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
            raise ValueError("args must be a list[str]")

    env: Optional[Dict[str, str]] = None

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = _resolve_workdir(repo_dir, workdir)

        rel_path = filename.strip() if isinstance(filename, str) and filename.strip() else None
        if rel_path is None:
            rel_path = f".mcp_tmp/run_python_{uuid.uuid4().hex}.py"

        rel_path = _safe_repo_relative_path(repo_dir, rel_path)
        abs_path = os.path.realpath(os.path.join(repo_dir, rel_path))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(script)

        install_result = None
        install_steps: list[Dict[str, Any]] = []
        if installing_dependencies and use_temp_venv:
            install_cmd = "python -m pip install -r dev-requirements.txt"
            install_result = await deps["run_shell"](
                install_cmd,
                cwd=cwd,
                timeout_seconds=max(600, timeout_seconds),
                env=env,
            )
            install_steps.append({"command": install_cmd, "result": install_result})
            if isinstance(install_result, dict) and install_result.get("exit_code", 0) != 0:
                i_stderr = install_result.get("stderr") or ""
                i_stdout = install_result.get("stdout") or ""
                raise GitHubAPIError(
                    "Dependency installation failed: " + (i_stderr.strip() or i_stdout.strip())
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
        return _structured_tool_error(exc, context="run_python", tool_surface="run_python")
    finally:
        if cleanup:
            try:
                deps = _tw()._workspace_deps()
                effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
                repo_dir = await deps["clone_repo"](
                    full_name, ref=effective_ref, preserve_changes=True
                )
                rel_path2 = (
                    filename.strip() if isinstance(filename, str) and filename.strip() else None
                )
                if rel_path2 is None:
                    # Only auto-cleanup when we created the file.
                    pass
                else:
                    rel_path2 = _safe_repo_relative_path(repo_dir, rel_path2)
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
# `run_command`, `run_shell`, or `run_terminal_commands`. To avoid breaking
# those callers, we keep lightweight MCP-tool aliases that forward to
# `terminal_command`.


@mcp_tool(write_action=True, name="run_command")
async def run_command_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
    """Backward-compatible alias for :func:`terminal_command`.

    This exists for older MCP clients that still invoke `run_command`.
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


@mcp_tool(write_action=True, name="run_shell")
async def run_shell_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
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


@mcp_tool(write_action=True, name="run_terminal_commands")
async def run_terminal_commands_alias(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    command_lines: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
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

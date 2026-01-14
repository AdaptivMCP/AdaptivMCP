# Split from github_mcp.tools_workspace (generated).
import os
import shlex
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _normalize_command_payload(
    command: str,
    command_lines: Optional[list[str]],
) -> tuple[str, list[str]]:
    """Normalize command inputs.

    Returns:
    - requested_command: the raw intended command (may contain newlines)
    - command_lines_out: list of command lines (is not supported contains newlines)
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


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _normalize_timeout_seconds(value: object, default: int) -> int:
    if value is None or isinstance(value, bool):
        return max(1, int(default))
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, float):
        return max(1, int(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return max(1, int(default))
        try:
            return max(1, int(float(s)))
        except Exception:
            return max(1, int(default))
    return max(1, int(default))


def _resolve_workdir(repo_dir: str, workdir: Optional[str]) -> str:
    if not workdir:
        return os.path.realpath(repo_dir)
    if not isinstance(workdir, str):
        raise ValueError("workdir must be a string")
    normalized = workdir.strip().replace("\\", "/")
    if not normalized:
        return os.path.realpath(repo_dir)
    if os.path.isabs(normalized):
        candidate = os.path.realpath(normalized)
    else:
        candidate = os.path.realpath(os.path.join(repo_dir, normalized))
    if not os.path.isdir(candidate):
        raise ValueError("workdir must point to a directory")
    return candidate


def _extract_missing_module(stdout: str, stderr: str) -> str:
    """Best-effort extraction of a missing module name from Python tracebacks."""
    combined = f"{stderr}\n{stdout}" if (stdout or stderr) else ""
    marker = "ModuleNotFoundError: No module named "
    pos = combined.find(marker)
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
    if lower.startswith("ruff ") or lower == "ruff":
        return ["ruff"]
    if lower.startswith("mypy ") or lower == "mypy" or "python -m mypy" in lower:
        return ["mypy"]
    if (
        lower.startswith("pytest")
        or " python -m pytest" in lower
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
    full_name: Optional[str] = None,
    *,
    command: str = "echo hello Render",
    command_lines: Optional[list[str]] = None,
    create_branch: Optional[str] = None,
    push_new_branch: bool = True,
    ref: str = "main",
    branch: Optional[str] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = False,
    installing_dependencies: bool = False,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Render-focused shell entry point for interacting with GitHub workspaces.

    The tool intentionally mirrors the Render deployment model by always
    operating through the server-side repo mirror (workspace clone). It ensures
    the repo mirror is cloned from the default branch (or a provided ref),
    optionally creates a fresh branch from that ref, and then executes the
    supplied shell command inside the repo mirror.
    """

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)

    try:
        requested_command, command_lines_out = _normalize_command_payload(
            command,
            command_lines,
        )

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)

        base_ref = _tw()._resolve_ref(ref, branch=branch)
        if not base_ref:
            base_ref = _tw()._default_branch_for_repo(full_name)
        effective_ref = _tw()._effective_ref_for_repo(full_name, base_ref)

        branch_creation: Optional[Dict[str, Any]] = None
        target_ref = effective_ref
        effective_branch_arg = effective_ref

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
                effective_branch_arg = create_branch
            else:
                # IMPORTANT: branch exists only locally in the base workcell (repo mirror).
                # Do NOT try to clone a non-existent remote branch.
                target_ref = effective_ref
                effective_branch_arg = effective_ref
                command = f"git checkout {shlex.quote(create_branch)} && {command}"

        command_result = await _tw().terminal_command(
            full_name=full_name,
            ref=target_ref,
            command=command,
            timeout_seconds=timeout_seconds,
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            owner=owner,
            repo=repo,
            branch=effective_branch_arg,
        )

        cleaned_command = command_result

        # logic can report exit code/stdout/stderr for render_shell as well.
        out: Dict[str, Any] = {
            "full_name": full_name,
            "base_ref": effective_ref,
            "target_ref": target_ref,
            "branch": branch_creation,
            "workdir": cleaned_command.get("workdir")
            if isinstance(cleaned_command, dict)
            else None,
            # Keep payload fields newline-free to avoid downstream double-escaping.
            "command_input": command,
            "command_lines": command_lines_out,
            "command": cleaned_command.get("command")
            if isinstance(cleaned_command, dict)
            else command,
            "install": cleaned_command.get("install")
            if isinstance(cleaned_command, dict)
            else None,
            "result": cleaned_command.get("result") if isinstance(cleaned_command, dict) else None,
        }
        return out
    except Exception as exc:
        return _structured_tool_error(exc, context="render_shell", tool_surface="render_shell")


@mcp_tool(write_action=True)
async def terminal_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    command_lines: Optional[list[str]] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = False,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a shell command inside the repo workcell and return its result.

    This supports tests, linters, or project scripts that need the real tree and
    virtualenv. The repo mirror (workspace clone) persists across calls so
    installed dependencies and edits are reused.
    """

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)

    env: Optional[Dict[str, str]] = None
    requested_command, command_lines_out = _normalize_command_payload(
        command,
        command_lines,
    )
    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = _resolve_workdir(repo_dir, workdir)

        install_result = None
        install_steps: list[Dict[str, Any]] = []
        retry_info: Dict[str, Any] = {"attempted": False, "packages": []}

        # Execute the raw intended command (may contain newlines if provided via command_lines).
        command = requested_command

        # Optional: install only *missing* dependencies (best-effort) when running
        # in a temp venv, then retry. This avoids proactively running
        # `pip install -r ...` but supports sequential missing-module installs.
        max_install_rounds = 3
        rounds = 0
        while True:
            result = await deps["run_shell"](
                command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                env=env,
            )

            if not (installing_dependencies and use_temp_venv):
                break

            cmd_lower = command.lower()
            already_installing = ("pip install" in cmd_lower) or ("pip3 install" in cmd_lower)
            exit_code = result.get("exit_code", 0) if isinstance(result, dict) else 0
            if already_installing or exit_code == 0:
                break

            if rounds >= max_install_rounds:
                break
            rounds += 1

            stdout = (result.get("stdout") or "") if isinstance(result, dict) else ""
            stderr = (result.get("stderr") or "") if isinstance(result, dict) else ""
            missing_module = _extract_missing_module(stdout, stderr)

            packages: list[str] = []
            if missing_module:
                packages = [missing_module]
            else:
                packages = _required_packages_for_command(command)

            if not packages:
                break

            retry_info = {"attempted": True, "packages": packages}
            install_cmd = "python -m pip install " + " ".join(packages)
            install_result = await deps["run_shell"](
                install_cmd,
                cwd=cwd,
                timeout_seconds=max(600, timeout_seconds),
                env=env,
            )
            install_steps.append(
                {
                    "packages": packages,
                    "command": install_cmd,
                    "result": install_result,
                }
            )
            if isinstance(install_result, dict) and install_result.get("exit_code", 0) != 0:
                i_stderr = install_result.get("stderr") or ""
                i_stdout = install_result.get("stdout") or ""
                raise GitHubAPIError(
                    "Dependency installation failed: "
                    + ((i_stderr.strip() or i_stdout.strip())[:2000])
                )

        out: Dict[str, Any] = {
            "workdir": cwd,
            # Keep payload fields newline-free to avoid downstream double-escaping.
            "command_input": command,
            "command_lines": command_lines_out,
            "command": command,
            "install": install_result,
            "install_steps": install_steps,
            "retry": retry_info,
            "result": result,
        }

        return out
    except Exception as exc:
        return _structured_tool_error(
            exc, context="terminal_command", tool_surface="terminal_command"
        )


# NOTE: The legacy tool name `run_command` has been removed.
# `terminal_command` replaces it.

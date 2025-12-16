# Split from github_mcp.tools_workspace (generated).
import os
import re
from typing import Any, Dict, Optional

from github_mcp.config import RUN_COMMAND_MAX_CHARS
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw
    return tw

@mcp_tool(write_action=False)
async def terminal_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a shell command inside the repo workspace and return its result.

    Use this for tests, linters, or project scripts that need the real tree and virtualenv. The workspace
    persists across calls so installed dependencies and edits are reused."""

    env: Optional[Dict[str, str]] = None
    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        if len(command) > RUN_COMMAND_MAX_CHARS:
            raise ValueError(
                f"run_command.command is too long ({len(command)} chars); "
                "split it into smaller commands or check in a script into the repo and run it from the workspace."
            )
        needs_write_gate = (
            mutating
            or installing_dependencies
            or not use_temp_venv
        )
        if needs_write_gate:
            # Prefer scoped write gating so feature-branch work is allowed even
            # when global WRITE_ALLOWED is disabled.
            try:
                deps["ensure_write_allowed"](
                    f"terminal_command {command} in {full_name}@{effective_ref}",
                    target_ref=effective_ref,
                )
            except TypeError:
                # Backwards-compat: older implementations accept only (context).
                deps["ensure_write_allowed"](
                    f"terminal_command {command} in {full_name}@{effective_ref}"
                )
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)

        # Optional dependency installation. If requested, install dev-requirements.txt (preferred)
        # or requirements.txt when present
        # (unless the command already appears to be installing deps).
        install_result = None
        if installing_dependencies and use_temp_venv:
            preferred = os.path.join(repo_dir, "dev-requirements.txt")
            fallback = os.path.join(repo_dir, "requirements.txt")
            req_path = preferred if os.path.exists(preferred) else fallback
            req_file = ("dev-requirements.txt" if os.path.exists(preferred) else "requirements.txt")
            cmd_lower = command.lower()
            already_installing = ("pip install" in cmd_lower) or ("pip3 install" in cmd_lower)
            if (not already_installing) and os.path.exists(req_path):
                install_result = await deps["run_shell"](
                    f"python -m pip install -r {req_file}",
                    cwd=cwd,
                    timeout_seconds=max(600, timeout_seconds),
                    env=env,
                )
                if isinstance(install_result, dict) and install_result.get("exit_code", 0) != 0:
                    stderr = install_result.get("stderr") or ""
                    stdout = install_result.get("stdout") or ""
                    raise GitHubAPIError(
                        "Dependency installation failed: " + (stderr.strip() or stdout.strip())
                    )

        result = await deps["run_shell"](
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        out: Dict[str, Any] = {
            "repo_dir": repo_dir,
            "workdir": workdir,
            "install": install_result,
            "result": result,
        }

        # If a python dependency is missing, nudge the assistant to rerun with deps installation.
        if (
            not installing_dependencies
            and isinstance(result, dict)
            and result.get("exit_code", 0) != 0
        ):
            stderr = result.get("stderr") or ""
            stdout = result.get("stdout") or ""
            combined = f"{stderr}\n{stdout}"
            mm = re.search(
                r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
                combined,
            )
            if mm:
                out["dependency_hint"] = {
                    "missing_module": mm.group(1),
                    "message": "Missing python dependency. Re-run terminal_command with installing_dependencies=true.",
                }

        return out
    except Exception as exc:
        return _structured_tool_error(exc, context="terminal_command")
@mcp_tool(write_action=False)
async def run_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Deprecated alias for terminal_command.

    Use terminal_command for a clearer "terminal/PC gateway" mental model.
    """

    out = await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
        owner=owner,
        repo=repo,
        branch=branch,
    )
    if isinstance(out, dict):
        log = out.get("controller_log")
        if not isinstance(log, list):
            log = []
        log.insert(0, "run_command is deprecated; use terminal_command instead.")
        out["controller_log"] = log
    return out
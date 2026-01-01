# Split from github_mcp.tools_workspace (generated).
import os
import shlex
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw
    return tw

def _strip_ui_fields(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    for k in ('controller_log', 'summary', 'user_message'):
        payload.pop(k, None)
    return payload

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




@mcp_tool(write_action=True)
async def render_shell(
    full_name: Optional[str] = None,
    *,
    command: str = "echo hello Render",
    create_branch: Optional[str] = None,
    push_new_branch: bool = True,
    ref: str = "main",
    branch: Optional[str] = None,
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)
    """Render-focused shell entry point for interacting with GitHub workspaces.

    The tool intentionally mirrors the Render deployment model by always
    operating through the server-side workspace clone. It ensures the workspace
    is cloned from the default branch (or a provided ref), optionally creates a
    fresh branch from that ref, and then executes the supplied shell command
    inside the clone.
    """

    try:
        requested_command = command
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
                # IMPORTANT: branch exists only locally in the base workspace.
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

        return {
            "full_name": full_name,
            "base_ref": effective_ref,
            "target_ref": target_ref,
            "branch": branch_creation,
            "command_input": requested_command,
            "command": command_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="render_shell", tool_surface="render_shell")


@mcp_tool(write_action=True)
async def terminal_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)
    """Run a shell command inside the repo workspace and return its result.

    Use this for tests, linters, or project scripts that need the real tree and virtualenv. The workspace
    persists across calls so installed dependencies and edits are reused."""

    env: Optional[Dict[str, str]] = None
    requested_command = command
    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)

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
            "workdir": workdir,
            "command_input": requested_command,
            "command": command,
            "install": install_result,
            "result": result,
        }

        if (
            not installing_dependencies
            and isinstance(result, dict)
            and result.get("exit_code", 0) != 0
        ):
            stderr = result.get("stderr") or ""
            stdout = result.get("stdout") or ""
            combined = f"{stderr}\n{stdout}"
            # Lightweight dependency hint (no regex).
            marker = 'ModuleNotFoundError: No module named '
            pos = combined.find(marker)
            if pos != -1:
                tail = combined[pos + len(marker):].strip()
                missing = ""
                if tail[:1] in ("\"", "'"):
                    q = tail[0]
                    tail2 = tail[1:]
                    endq = tail2.find(q)
                    missing = tail2[:endq] if endq != -1 else tail2
                else:
                    missing = tail.split()[0] if tail else ""
                missing = (missing or "").strip()
                if missing:
                    out["dependency_hint"] = {
                        "missing_module": missing,
                        "message": "Missing python dependency. Re-run terminal_command with installing_dependencies=true.",
                    }
        out = _strip_ui_fields(out)

        return out
    except Exception as exc:
        return _structured_tool_error(exc, context="terminal_command", tool_surface="terminal_command")


@mcp_tool(write_action=True, visibility="hidden")
async def run_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: float = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 300)
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

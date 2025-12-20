from __future__ import annotations

import re
from typing import Any, Optional

from github_mcp.mcp_server.decorators import mcp_tool
from github_mcp.workspace_tools._shared import run_in_workspace


_GIT_PUSH_RE = re.compile(r"(?m)(^|\s)git\s+push(\s|$)")


def _contains_git_push(command: str) -> bool:
    return bool(_GIT_PUSH_RE.search(command or ""))


@mcp_tool()
async def terminal_command(
    full_name: str,
    ref: str,
    command: str,
    timeout_seconds: int = 120,
    use_temp_venv: bool = False,
    mutating: bool = False,
) -> Any:
    """
    Run a shell command in the persistent workspace clone.

    Safety:
    - `git push` is NOT allowed here. Use `terminal_push` so UI prompting is correct.
    """
    if _contains_git_push(command):
        raise ValueError(
            "Blocked: `git push` must be executed via the `terminal_push` tool "
            "so the client can require explicit approval."
        )

    return await run_in_workspace(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        use_temp_venv=use_temp_venv,
        mutating=mutating,
    )


@mcp_tool(write_action=True)
async def terminal_push(
    full_name: str,
    ref: str,
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
    force: bool = False,
    timeout_seconds: int = 180,
    use_temp_venv: bool = False,
) -> Any:
    """
    Push the current workspace branch to GitHub.

    This is intentionally a separate tool so it can be marked consequential and
    consistently require an approval prompt when auto-approve is off, and also
    be the only supported way to push when auto-approve is on.
    """
    args = ["git", "push"]
    if set_upstream:
        args.append("--set-upstream")
    if force:
        args.append("--force")
    args.append(remote)
    if branch:
        args.append(branch)

    cmd = " ".join(args)

    return await run_in_workspace(
        full_name=full_name,
        ref=ref,
        command=cmd,
        timeout_seconds=timeout_seconds,
        use_temp_venv=use_temp_venv,
        mutating=True,
    )
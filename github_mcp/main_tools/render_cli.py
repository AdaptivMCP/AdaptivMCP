from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any, Dict, List, Optional

from github_mcp.exceptions import UsageError


def _ensure_render_cli_available() -> None:
    if shutil.which("render"):
        return
    raise UsageError(
        "Render CLI is not installed in this runtime. If you're running on Render, rebuild the service (Dockerfile installs it)."
    )


def _maybe_append_flag(args: List[str], flag: str, value: Optional[str] = None) -> List[str]:
    if flag in args:
        return args
    if value is None:
        return [*args, flag]
    return [*args, flag, value]


async def run_render_cli(
    *,
    args: List[str],
    output: str = "json",
    confirm: bool = True,
    timeout_seconds: int = 120,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the Render CLI and return a structured result.

    Notes:
    - Requires RENDER_API_KEY to be set in the environment.
    - Uses non-interactive flags by default.
    """

    if not args:
        raise UsageError("args must be a non-empty list")

    _ensure_render_cli_available()

    env = os.environ.copy()
    if not env.get("RENDER_API_KEY"):
        raise UsageError(
            "RENDER_API_KEY is not set. Add it to the service environment variables to use the Render CLI."
        )

    cli_args = list(args)

    # Prefer non-interactive, parseable output.
    if output:
        cli_args = _maybe_append_flag(cli_args, "--output", output)
    if confirm:
        cli_args = _maybe_append_flag(cli_args, "--confirm")

    proc = await asyncio.create_subprocess_exec(
        "render",
        *cli_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        proc.kill()
        stdout_b, stderr_b = await proc.communicate()

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")

    parsed = None
    if output == "json" and stdout.strip():
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None

    return {
        "command": ["render", *cli_args],
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "json": parsed,
    }

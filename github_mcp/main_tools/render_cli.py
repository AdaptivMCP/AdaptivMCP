"""Render CLI wrapper for non-interactive commands.

Tool implementations for the main MCP surface.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import platform
import urllib.request

from github_mcp.exceptions import UsageError


_RENDER_CLI_PATH: Optional[str] = None


def _platform_asset_name(tag: str) -> str:
    """Return the expected Render CLI zip asset name for this runtime."""

    # tag looks like: v2.6.1
    version = tag[1:] if tag.startswith("v") else tag

    sys = platform.system().lower()
    if sys != "linux":
        raise UsageError(f"Render CLI auto-install currently supports linux only (got {sys}).")

    arch = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    arch = arch_map.get(arch)
    if not arch:
        raise UsageError(
            f"Unsupported architecture for Render CLI auto-install: {platform.machine()}"
        )

    return f"cli_{version}_{sys}_{arch}.zip"


def _download_latest_release_metadata() -> Dict[str, Any]:
    url = "https://api.github.com/repos/render-oss/cli/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-mcp-server",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _install_render_cli() -> str:
    """Download and cache the Render CLI binary, returning the full path."""

    meta = _download_latest_release_metadata()
    tag = meta.get("tag_name")
    if not tag:
        raise UsageError("Unable to determine latest Render CLI release tag from GitHub API.")

    asset_name = _platform_asset_name(tag)
    assets = meta.get("assets") or []

    download_url = None
    for a in assets:
        if a.get("name") == asset_name:
            download_url = a.get("browser_download_url")
            break

    if not download_url:
        raise UsageError(f"Could not find Render CLI asset {asset_name} in release {tag}.")

    base_dir = Path(os.environ.get("RENDER_CLI_DIR", "/tmp/render-cli")).expanduser()
    install_dir = base_dir / tag
    install_dir.mkdir(parents=True, exist_ok=True)

    bin_path = install_dir / "render"
    if bin_path.exists():
        return str(bin_path)

    req = urllib.request.Request(
        download_url,
        headers={"User-Agent": "github-mcp-server"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()

    z = zipfile.ZipFile(BytesIO(blob))
    # Expect a single binary named like cli_v2.6.1 plus LICENSE/README.
    candidates = [n for n in z.namelist() if n.startswith("cli_v")]
    if not candidates:
        raise UsageError("Render CLI zip did not contain an expected cli_v* binary.")

    cli_name = candidates[0]
    data = z.read(cli_name)
    bin_path.write_bytes(data)
    bin_path.chmod(0o755)

    return str(bin_path)


def _ensure_render_cli_available() -> str:
    global _RENDER_CLI_PATH

    # Cached
    if _RENDER_CLI_PATH and Path(_RENDER_CLI_PATH).exists():
        return _RENDER_CLI_PATH

    # System
    existing = shutil.which("render")
    if existing:
        _RENDER_CLI_PATH = existing
        return existing

    # Auto-install
    _RENDER_CLI_PATH = _install_render_cli()
    return _RENDER_CLI_PATH


async def _run_cli_once(
    render_bin: str,
    args: List[str],
    *,
    env: Dict[str, str],
    timeout_seconds: int = 30,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        render_bin,
        *args,
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

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }


async def _ensure_workspace_selected(
    *,
    render_bin: str,
    env: Dict[str, str],
    timeout_seconds: int = 30,
) -> None:
    """Ensure the Render CLI has an active workspace selected.

    The Render CLI requires a workspace to be set before most commands. We support
    auto-selecting a workspace if one of these is present in env:
      - RENDER_WORKSPACE_ID
      - RENDER_WORKSPACE_NAME
      - RENDER_OWNER_ID (Render-provided; treated as workspace id)

    Workspace selection is stored in a config file; we default it to a safe
    writable path if RENDER_CLI_CONFIG_PATH is not set.
    """

    # Ensure config path is writable (Render containers may not have a real HOME).
    if not env.get("RENDER_CLI_CONFIG_PATH"):
        env["RENDER_CLI_CONFIG_PATH"] = "/tmp/render-cli/cli.yaml"

    # First check if already set.
    current = await _run_cli_once(
        render_bin,
        ["workspace", "current", "--output", "text", "--confirm"],
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if current.get("exit_code") == 0:
        return

    ws = (
        env.get("RENDER_WORKSPACE_ID")
        or env.get("RENDER_WORKSPACE_NAME")
        or env.get("RENDER_OWNER_ID")
        or ""
    ).strip()
    if not ws:
        raise UsageError(
            "Render CLI has no workspace selected. Set RENDER_WORKSPACE_ID (or RENDER_WORKSPACE_NAME) in env so the controller can auto-select it. If running on Render, RENDER_OWNER_ID will be used automatically when present."
        )

    set_res = await _run_cli_once(
        render_bin,
        ["workspace", "set", ws, "--output", "text", "--confirm"],
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if set_res.get("exit_code") != 0:
        err = (set_res.get("stderr") or set_res.get("stdout") or "").strip()
        raise UsageError(f"Failed to set Render CLI workspace ({ws}): {err}")


_HELP_ROOT_FLAGS = {"--help", "-h", "--version", "-v"}


def _should_inject_global_flags(args: List[str]) -> bool:
    """Return True if we should auto-append global flags like --output/--confirm.

    Render CLI has a quirk: `render --help --output json` errors because `--help`
    at the root command level stops normal flag parsing. To keep the wrapper
    usable for `--help`/`--version`, we skip injecting flags when the *first*
    argument is a root help/version flag.
    """

    return not (args and args[0] in _HELP_ROOT_FLAGS)


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
    - If the Render CLI binary is missing, this function will auto-download it.
    """

    if not args:
        raise UsageError("args must be a non-empty list")

    env = os.environ.copy()
    if not env.get("RENDER_API_KEY"):
        raise UsageError(
            "RENDER_API_KEY is not set. Add it to the service environment variables to use the Render CLI."
        )

    render_bin = _ensure_render_cli_available()

    await _ensure_workspace_selected(
        render_bin=render_bin, env=env, timeout_seconds=min(timeout_seconds, 30)
    )

    cli_args = list(args)

    inject_flags = _should_inject_global_flags(cli_args)

    # Prefer non-interactive, parseable output.
    if inject_flags and output:
        cli_args = _maybe_append_flag(cli_args, "--output", output)
    if inject_flags and confirm:
        cli_args = _maybe_append_flag(cli_args, "--confirm")

    proc = await asyncio.create_subprocess_exec(
        render_bin,
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
        "command": [render_bin, *cli_args],
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "json": parsed,
    }

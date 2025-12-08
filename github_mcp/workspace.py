"""Workspace and shell helpers for GitHub MCP tools."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, Optional

from . import config
from .exceptions import GitHubAPIError
from .http_clients import _get_github_token


async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a shell command with author/committer env vars injected."""

    shell_executable = os.environ.get("SHELL")
    if os.name == "nt":
        shell_executable = shell_executable or shutil.which("bash")

    main_module = sys.modules.get("main")
    proc_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": getattr(main_module, "GIT_AUTHOR_NAME", config.GIT_AUTHOR_NAME),
        "GIT_AUTHOR_EMAIL": getattr(main_module, "GIT_AUTHOR_EMAIL", config.GIT_AUTHOR_EMAIL),
        "GIT_COMMITTER_NAME": getattr(main_module, "GIT_COMMITTER_NAME", config.GIT_COMMITTER_NAME),
        "GIT_COMMITTER_EMAIL": getattr(
            main_module, "GIT_COMMITTER_EMAIL", config.GIT_COMMITTER_EMAIL
        ),
    }
    if env is not None:
        proc_env.update(env)

    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable=shell_executable,
        env=proc_env,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
        timed_out = True

    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
    raw_stderr = stderr_bytes.decode("utf-8", errors="replace")
    stdout = raw_stdout
    stderr = raw_stderr
    stdout_truncated = False
    stderr_truncated = False

    stdout_limit = getattr(main_module, "TOOL_STDOUT_MAX_CHARS", config.TOOL_STDOUT_MAX_CHARS)
    if stdout_limit and stdout_limit > 0 and len(stdout) > stdout_limit:
        stdout = stdout[:stdout_limit]
        stdout_truncated = True

    stderr_limit = getattr(main_module, "TOOL_STDERR_MAX_CHARS", config.TOOL_STDERR_MAX_CHARS)
    if stderr_limit and stderr_limit > 0 and len(stderr) > stderr_limit:
        stderr = stderr[:stderr_limit]
        stderr_truncated = True

    combined_limit = getattr(
        main_module, "TOOL_STDIO_COMBINED_MAX_CHARS", config.TOOL_STDIO_COMBINED_MAX_CHARS
    )
    if combined_limit and combined_limit > 0 and len(stdout) + len(stderr) > combined_limit:
        allowed_stdout = max(0, combined_limit - len(stderr))
        if len(stdout) > allowed_stdout:
            stdout = stdout[:allowed_stdout]
            stdout_truncated = True

        if len(stdout) + len(stderr) > combined_limit:
            allowed_stderr = max(0, combined_limit - len(stdout))
            if len(stderr) > allowed_stderr:
                stderr = stderr[:allowed_stderr]
                stderr_truncated = True

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def _workspace_path(full_name: str, ref: str) -> str:
    repo_key = full_name.replace("/", "__")
    ref_key = ref.replace("/", "__")
    main_module = sys.modules.get("main")
    base_dir = getattr(main_module, "WORKSPACE_BASE_DIR", config.WORKSPACE_BASE_DIR)
    return os.path.join(base_dir, repo_key, ref_key)


async def _clone_repo(
    full_name: str, ref: Optional[str] = None, *, preserve_changes: bool = False
) -> str:
    """Clone or return a persistent workspace for ``full_name``/``ref``."""

    from .utils import _effective_ref_for_repo  # Local import to avoid cycles

    effective_ref = _effective_ref_for_repo(full_name, ref)
    workspace_dir = _workspace_path(full_name, effective_ref)
    os.makedirs(os.path.dirname(workspace_dir), exist_ok=True)

    main_module = sys.modules.get("main")
    run_shell = getattr(main_module, "_run_shell", _run_shell)

    if os.path.isdir(os.path.join(workspace_dir, ".git")):
        if preserve_changes:
            fetch_result = await run_shell(
                "git fetch origin --prune",
                cwd=workspace_dir,
                timeout_seconds=300,
            )
            if fetch_result["exit_code"] != 0:
                stderr = fetch_result.get("stderr", "") or fetch_result.get("stdout", "")
                raise GitHubAPIError(
                    f"Workspace fetch failed for {full_name}@{effective_ref}: {stderr}"
                )

            return workspace_dir

        refresh_steps = [
            ("git fetch origin --prune", 300),
            (f"git reset --hard origin/{effective_ref}", 120),
            (
                "git clean -fdx --exclude .venv-mcp",
                120,
            ),
        ]

        for cmd, timeout in refresh_steps:
            result = await run_shell(cmd, cwd=workspace_dir, timeout_seconds=timeout)
            if result["exit_code"] != 0:
                stderr = result.get("stderr", "") or result.get("stdout", "")
                raise GitHubAPIError(
                    f"Workspace refresh failed for {full_name}@{effective_ref}: {stderr}"
                )

        return workspace_dir

    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)

    tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
    token = _get_github_token()

    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {effective_ref} {url} {tmpdir}"
    result = await run_shell(cmd, cwd=None, timeout_seconds=600)
    if result["exit_code"] != 0:
        stderr = result.get("stderr", "")
        raise GitHubAPIError(f"git clone failed: {stderr}")

    shutil.move(tmpdir, workspace_dir)
    return workspace_dir


async def _prepare_temp_virtualenv(repo_dir: str) -> Dict[str, str]:
    """Create an isolated virtualenv and return env vars that activate it."""

    main_module = sys.modules.get("main")
    run_shell = getattr(main_module, "_run_shell", _run_shell)

    venv_dir = os.path.join(repo_dir, ".venv-mcp")
    if os.path.isdir(venv_dir):
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        bin_path = os.path.join(venv_dir, bin_dir)
        return {
            "VIRTUAL_ENV": venv_dir,
            "PATH": f"{bin_path}{os.pathsep}" + os.environ.get("PATH", ""),
        }

    result = await run_shell(
        f"{sys.executable} -m venv {venv_dir}",
        cwd=repo_dir,
        timeout_seconds=300,
    )
    if result["exit_code"] != 0:
        stderr = result.get("stderr", "") or result.get("stdout", "")
        raise GitHubAPIError(f"Failed to create temp virtualenv: {stderr}")

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    bin_path = os.path.join(venv_dir, bin_dir)
    return {
        "VIRTUAL_ENV": venv_dir,
        "PATH": f"{bin_path}{os.pathsep}" + os.environ.get("PATH", ""),
    }


async def _apply_patch_to_repo(repo_dir: str, patch: str) -> None:
    """Write a unified diff to disk and apply it with ``git apply``."""

    if not patch or not patch.strip():
        raise GitHubAPIError("Received empty patch to apply in workspace")

    patch_path = os.path.join(repo_dir, "mcp_patch.diff")
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch)

    apply_result = await _run_shell(
        f"git apply --whitespace=nowarn {patch_path}",
        cwd=repo_dir,
        timeout_seconds=60,
    )
    if apply_result["exit_code"] != 0:
        stderr = apply_result.get("stderr", "") or apply_result.get("stdout", "")
        raise GitHubAPIError(f"git apply failed while preparing workspace: {stderr}")


__all__ = [
    "_apply_patch_to_repo",
    "_clone_repo",
    "_prepare_temp_virtualenv",
    "_run_shell",
    "_workspace_path",
]

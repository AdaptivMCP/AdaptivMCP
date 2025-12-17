"""Workspace and shell helpers for GitHub MCP tools."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, Optional

from . import config
from .exceptions import GitHubAPIError
from .http_clients import _get_github_token

TOKEN_PATTERNS = [
    (
        re.compile(r"https://x-access-token:([^@/\s]+)@github\.com/"),  # tokenlike-allow
        "https://x-access-token:***@github.com/",  # tokenlike-allow
    ),
    (
        re.compile(r"x-access-token:([^@\s]+)@github\.com"),
        "x-access-token:***@github.com",  # tokenlike-allow
    ),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "ghp_***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github_pat_***"),
]


# Strip ANSI/control characters from command output so connector UIs don't
# render escape sequences (spinners, colors, cursor controls) as random characters.
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x1B]*(?:\x1B\\\\|\x07))")
# Preserve \"\n\" and \"\t\"; normalize \"\r\" to newlines before stripping.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_tty_output(value: str) -> str:
    if not value:
        return value
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _ANSI_ESCAPE_RE.sub("", value)
    value = _CONTROL_CHARS_RE.sub("", value)
    return value


def _redact_sensitive(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pat, repl in TOKEN_PATTERNS:
        redacted = pat.sub(repl, redacted)
    try:
        tok = _get_github_token()
        if tok and isinstance(tok, str):
            redacted = redacted.replace(tok, "***")
    except Exception:
        pass
    return redacted


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

    start_new_session = os.name != "nt"
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable=shell_executable,
        env=proc_env,
        start_new_session=start_new_session,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
        # Best-effort termination: kill the whole process group on POSIX so
        # child processes (e.g. pytest workers) don't keep pipes open.
        if os.name != "nt":
            import signal

            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        else:
            try:
                proc.kill()
            except Exception:
                pass

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
        except Exception:
            stdout_bytes, stderr_bytes = b"", b""

    raw_stdout = _sanitize_tty_output(stdout_bytes.decode("utf-8", errors="replace"))
    raw_stderr = _sanitize_tty_output(stderr_bytes.decode("utf-8", errors="replace"))
    stdout = _redact_sensitive(raw_stdout)
    stderr = _redact_sensitive(raw_stderr)
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

        # If the workspace has local edits (tracked or untracked), avoid destructive
        # refresh so a non-mutating terminal_command call cannot wipe in-progress work.
        status = await run_shell("git status --porcelain", cwd=workspace_dir, timeout_seconds=60)
        if status["exit_code"] != 0:
            stderr = status.get("stderr", "") or status.get("stdout", "")
            raise GitHubAPIError(
                f"Workspace status failed for {full_name}@{effective_ref}: {stderr}"
            )

        dirty_lines: list[str] = []
        for raw in (status.get("stdout", "") or "").splitlines():
            raw = raw.rstrip()
            if not raw:
                continue
            # Porcelain format: XY <path> (or ?? <path>)
            path = raw[3:].strip() if len(raw) >= 4 else raw
            if path == ".venv-mcp" or path.startswith(".venv-mcp/"):
                continue
            dirty_lines.append(raw)

        if dirty_lines:
            fetch_result = await run_shell(
                "git fetch origin --prune", cwd=workspace_dir, timeout_seconds=300
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

    url = f"https://x-access-token:{token}@github.com/{full_name}.git"  # tokenlike-allow
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


def _maybe_unescape_unified_diff(patch: str) -> str:
    """Coerce a unified diff into newline-delimited text.

    Some upstream callers accidentally double-escape diffs (e.g. a single-line
    string containing literal \\n sequences). This breaks header parsing and
    `git apply`. We only unescape when the input looks like an escaped diff and
    contains no real newlines.
    """

    if not isinstance(patch, str):
        return patch

    # Already a normal multi-line diff.
    if "\n" in patch:
        return patch

    if "\\n" not in patch:
        return patch

    looks_like_diff = (
        patch.lstrip().startswith("diff --git ")
        or patch.lstrip().startswith("--- ")
        or "diff --git " in patch
        or "--- " in patch
        or "+++ " in patch
        or "@@ " in patch
    )
    if not looks_like_diff:
        return patch

    try:
        return patch.encode("utf-8").decode("unicode_escape")
    except Exception:
        return patch.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def _sanitize_patch_head(patch: str) -> str:
    """Strip common leading junk that breaks `git apply`.

    Common failure cases:
    - Patches wrapped in markdown fences (```diff ... ```)
    - Patches prefixed with stray JSON braces or assistant metadata

    We only strip when the input looks like a diff somewhere in the text.
    """

    if not isinstance(patch, str):
        return patch

    # Normalize line endings early.
    patch = patch.replace("\r\n", "\n")

    looks_like_diff = (
        patch.lstrip().startswith("diff --git ")
        or patch.lstrip().startswith("--- ")
        or "diff --git " in patch
        or "--- " in patch
        or "+++ " in patch
        or "@@ " in patch
    )
    if not looks_like_diff:
        return patch

    lines = patch.splitlines()

    # Remove leading blank lines.
    while lines and not lines[0].strip():
        lines.pop(0)

    # Remove leading markdown fences.
    if lines and lines[0].strip().startswith("```"):
        lines.pop(0)
        # Some callers include a blank line after the fence.
        while lines and not lines[0].strip():
            lines.pop(0)

    # If the diff starts later (e.g., after some chatter), drop everything before it.
    start_idx = None
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("diff --git ") or s.startswith("--- "):
            start_idx = i
            break
    if start_idx is not None and start_idx > 0:
        lines = lines[start_idx:]

    return "\n".join(lines) + ("\n" if patch.endswith("\n") else "")


def _sanitize_patch_tail(patch: str) -> str:
    """Strip common trailing junk that breaks `git apply`.

    Guards against accidental JSON/Markdown artifacts being appended to patches
    (e.g. `}}`, code fences), which commonly yields:
    - "corrupt patch"
    - "No valid patches in input"
    """

    if not isinstance(patch, str):
        return patch

    # Only attempt to strip trailing junk when the input actually looks like a diff.
    # This avoids surprising behavior for arbitrary strings that may legitimately end
    # with code fences or braces.
    looks_like_diff = (
        patch.lstrip().startswith("diff --git ")
        or patch.lstrip().startswith("--- ")
        or "diff --git " in patch
        or "--- " in patch
        or "+++ " in patch
        or "@@ " in patch
    )
    if not looks_like_diff:
        return patch

    ends_with_nl = patch.endswith("\n")
    lines = patch.splitlines()

    junk_lines = {"}", "}}", "```", "```diff", "```patch"}
    while lines and lines[-1].strip() in junk_lines:
        lines.pop()

    out = "\n".join(lines)
    if ends_with_nl and out and not out.endswith("\n"):
        out += "\n"
    return out


async def _apply_patch_to_repo(repo_dir: str, patch: str) -> None:
    """Write a unified diff to disk and apply it with ``git apply``."""

    if not patch or not patch.strip():
        raise GitHubAPIError("Received empty patch to apply in workspace")

    patch = _maybe_unescape_unified_diff(patch)
    patch = _sanitize_patch_head(patch)
    patch = _sanitize_patch_tail(patch)

    patch_path = os.path.join(repo_dir, "mcp_patch.diff")

    if patch and not patch.endswith("\n"):
        patch = patch + "\n"

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

"""Workspace and shell helpers for GitHub MCP tools."""

from __future__ import annotations

import asyncio
import base64
import os
import hashlib
import re
import shutil
import shlex
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .exceptions import GitHubAPIError, GitHubAuthError
from .http_clients import _get_github_token
from .utils import _get_main_module


def _is_git_rate_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        marker in lowered for marker in ("rate limit", "secondary rate limit", "abuse detection")
    )


async def _run_git_with_retry(
    run_shell,
    cmd: str,
    *,
    cwd: Optional[str],
    timeout_seconds: int,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    attempt = 0
    max_attempts = max(0, config.GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS)

    while True:
        result = await run_shell(
            cmd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        if result.get("exit_code", 0) == 0:
            return result

        stderr = result.get("stderr", "") or result.get("stdout", "")
        if _is_git_rate_limit_error(stderr) and attempt < max_attempts:
            delay = config.GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS * (2**attempt)
            delay = min(delay, config.GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS)
            await asyncio.sleep(delay)
            attempt += 1
            continue

        return result


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

    main_module = _get_main_module()
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

    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
    raw_stderr = stderr_bytes.decode("utf-8", errors="replace")

    # No truncation (by request).
    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": raw_stdout,
        "stderr": raw_stderr,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }


def _append_git_config_env(env: Dict[str, str], key: str, value: str) -> None:
    """
    Append a git config entry via environment variables (GIT_CONFIG_COUNT, etc.).
    This avoids putting secrets on the command line.
    """
    # Git reads these: GIT_CONFIG_COUNT, GIT_CONFIG_KEY_<n>, GIT_CONFIG_VALUE_<n>
    try:
        existing = int(env.get("GIT_CONFIG_COUNT", "0") or "0")
    except Exception:
        existing = 0

    idx = existing
    env["GIT_CONFIG_COUNT"] = str(existing + 1)
    env[f"GIT_CONFIG_KEY_{idx}"] = key
    env[f"GIT_CONFIG_VALUE_{idx}"] = value


def _git_auth_env() -> Dict[str, str]:
    env: Dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
    try:
        token = _get_github_token()
    except GitHubAuthError:
        return env

    # GitHub supports basic auth with username "x-access-token" and the token as password.
    basic_token = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("utf-8")
    header_value = f"Authorization: Basic {basic_token}"

    # Correct name (no extra underscore).
    env["GIT_HTTP_EXTRAHEADER"] = header_value
    # Back-compat for any code that mistakenly used the wrong name.
    env["GIT_HTTP_EXTRA_HEADER"] = header_value

    # Also set via config-env to improve compatibility across git builds.
    _append_git_config_env(env, "http.extraHeader", header_value)

    return env


def _git_env_has_auth_header(env: Dict[str, str]) -> bool:
    if env.get("GIT_HTTP_EXTRAHEADER") or env.get("GIT_HTTP_EXTRA_HEADER"):
        return True
    for key, value in env.items():
        if key.startswith("GIT_CONFIG_KEY_") and value == "http.extraHeader":
            return True
    return False


def _git_no_auth_env() -> Dict[str, str]:
    return {"GIT_TERMINAL_PROMPT": "0"}


def _is_git_auth_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        fragment in lowered
        for fragment in (
            "terminal prompts disabled",
            "could not read username",
            "could not read password",
            "authentication failed",
            "invalid username or password",
        )
    )


def _raise_git_auth_error(operation: str, stderr: str) -> None:
    if not _is_git_auth_error(stderr):
        return

    # Best-effort context without dumping huge logs. Do not include any env content here.
    excerpt = " ".join((stderr or "").replace("\r", " ").replace("\n", " ").split())
    if len(excerpt) > 240:
        excerpt = excerpt[:240] + "..."

    raise GitHubAuthError(
        f"{operation} failed with an authentication-like git error while prompts are disabled. "
        f"git stderr (excerpt): {excerpt} "
        "Provide GitHub repo credentials via a connector/credential helper or a supported env var "
        "(GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN), or ensure the repo is public."
    )


def _workspace_path(full_name: str, ref: str) -> str:
    repo_key = full_name.replace("/", "__")

    main_module = _get_main_module()
    base_dir = getattr(main_module, "WORKSPACE_BASE_DIR", config.WORKSPACE_BASE_DIR)

    safe_ref = _sanitize_workspace_ref(ref)

    workspace_dir = os.path.join(base_dir, repo_key, safe_ref)

    return workspace_dir


_WORKSPACE_REF_MAX_LEN = 80


def _sanitize_workspace_ref(ref: str) -> str:
    """Convert an arbitrary ref string into a safe workspace directory name.

    The returned value is guaranteed to be a single path segment (no path
    separators) and stable for the same input.
    """

    if not isinstance(ref, str) or not ref.strip():
        return "main"

    raw = ref.strip()

    # Normalize separators and strip leading slashes to avoid absolute paths.
    raw = raw.replace("\\", "/").lstrip("/")

    # Collapse separators and Windows drive markers into safe tokens.
    raw = raw.replace("/", "__").replace(":", "__")

    # Allow a conservative set of characters; replace the rest.
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)

    # Collapse runs and trim punctuation.
    slug = re.sub(r"_+", "_", slug).strip("._-")

    if not slug:
        return "main"

    if len(slug) <= _WORKSPACE_REF_MAX_LEN:
        return slug

    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
    head = slug[: _WORKSPACE_REF_MAX_LEN - 13].rstrip("._-")
    if not head:
        head = "ref"
    return f"{head}-{digest}"


async def _clone_repo(
    full_name: str, ref: Optional[str] = None, *, preserve_changes: bool = False
) -> str:
    """Clone or return a persistent workspace for ``full_name``/``ref``."""
    from .utils import _effective_ref_for_repo  # Local import to avoid cycles

    effective_ref = _effective_ref_for_repo(full_name, ref)
    workspace_dir = _workspace_path(full_name, effective_ref)
    os.makedirs(os.path.dirname(workspace_dir), exist_ok=True)

    main_module = _get_main_module()
    run_shell = getattr(main_module, "_run_shell", _run_shell)
    auth_env = _git_auth_env()
    no_auth_env = _git_no_auth_env()
    git_env = auth_env

    if os.path.isdir(os.path.join(workspace_dir, ".git")):
        if preserve_changes:
            fetch_result = await _run_git_with_retry(
                run_shell,
                "git fetch origin --prune",
                cwd=workspace_dir,
                timeout_seconds=300,
                env=git_env,
            )
            if fetch_result["exit_code"] != 0:
                stderr = fetch_result.get("stderr", "") or fetch_result.get("stdout", "")
                if _is_git_auth_error(stderr) and _git_env_has_auth_header(git_env):
                    fetch_result = await _run_git_with_retry(
                        run_shell,
                        "git fetch origin --prune",
                        cwd=workspace_dir,
                        timeout_seconds=300,
                        env=no_auth_env,
                    )
                    if fetch_result["exit_code"] == 0:
                        git_env = no_auth_env
                        return workspace_dir
                    stderr = fetch_result.get("stderr", "") or fetch_result.get("stdout", "")
                _raise_git_auth_error("Workspace fetch", stderr)
                raise GitHubAPIError(
                    f"Workspace fetch failed for {full_name}@{effective_ref}: {stderr}"
                )

            return workspace_dir

        q_ref = shlex.quote(effective_ref)
        refresh_steps = [
            ("git fetch origin --prune", 300),
            (f"git reset --hard origin/{q_ref}", 120),
            ("git clean -fdx --exclude .venv-mcp", 120),
        ]

        for cmd, timeout in refresh_steps:
            result = await _run_git_with_retry(
                run_shell,
                cmd,
                cwd=workspace_dir,
                timeout_seconds=timeout,
                env=git_env,
            )
            if result["exit_code"] != 0:
                stderr = result.get("stderr", "") or result.get("stdout", "")
                if _is_git_auth_error(stderr) and _git_env_has_auth_header(git_env):
                    result = await _run_git_with_retry(
                        run_shell,
                        cmd,
                        cwd=workspace_dir,
                        timeout_seconds=timeout,
                        env=no_auth_env,
                    )
                    if result["exit_code"] == 0:
                        git_env = no_auth_env
                        continue
                    stderr = result.get("stderr", "") or result.get("stdout", "")
                _raise_git_auth_error("Workspace refresh", stderr)
                raise GitHubAPIError(
                    f"Workspace refresh failed for {full_name}@{effective_ref}: {stderr}"
                )

        return workspace_dir

    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)

    tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
    url = f"https://github.com/{full_name}.git"
    q_ref = shlex.quote(effective_ref)
    q_url = shlex.quote(url)
    q_tmpdir = shlex.quote(tmpdir)
    cmd = f"git clone --depth 1 --branch {q_ref} {q_url} {q_tmpdir}"
    result = await _run_git_with_retry(
        run_shell,
        cmd,
        cwd=None,
        timeout_seconds=600,
        env=git_env,
    )
    if result["exit_code"] != 0:
        stderr = result.get("stderr", "") or result.get("stdout", "")
        if _is_git_auth_error(stderr) and _git_env_has_auth_header(git_env):
            shutil.rmtree(tmpdir, ignore_errors=True)
            tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
            q_tmpdir = shlex.quote(tmpdir)
            cmd = f"git clone --depth 1 --branch {q_ref} {q_url} {q_tmpdir}"
            result = await _run_git_with_retry(
                run_shell,
                cmd,
                cwd=None,
                timeout_seconds=600,
                env=no_auth_env,
            )
            if result["exit_code"] == 0:
                shutil.move(tmpdir, workspace_dir)
                return workspace_dir
            stderr = result.get("stderr", "") or result.get("stdout", "")
        _raise_git_auth_error("git clone", stderr)
        raise GitHubAPIError(f"git clone failed: {stderr}")

    shutil.move(tmpdir, workspace_dir)
    return workspace_dir


async def _prepare_temp_virtualenv(repo_dir: str) -> Dict[str, str]:
    """Create an isolated virtualenv and return env vars that activate it."""
    main_module = _get_main_module()
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


def _safe_repo_path(repo_dir: str, rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise GitHubAPIError("path must be a non-empty string")
    root = os.path.realpath(repo_dir)
    raw_path = rel_path.strip()
    if os.path.isabs(raw_path):
        candidate = os.path.realpath(raw_path)
    else:
        rel_path = raw_path.lstrip("/\\")
        candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
    if candidate == root or not candidate.startswith(root + os.sep):
        raise GitHubAPIError("path escapes repository root")
    return candidate


def _split_text_lines(text: str) -> Tuple[List[str], bool]:
    ends_with_newline = text.endswith("\n")
    lines = text.splitlines()
    return lines, ends_with_newline


def _join_text_lines(lines: List[str], ends_with_newline: bool) -> str:
    text = "\n".join(lines)
    if ends_with_newline and (text or lines):
        text = text + "\n"
    return text


def _find_subsequence(lines: List[str], subseq: List[str], start: int) -> Optional[int]:
    if not subseq:
        return start
    max_idx = len(lines) - len(subseq)
    for idx in range(start, max_idx + 1):
        if lines[idx : idx + len(subseq)] == subseq:
            return idx
    return None


def _apply_patch_hunks(lines: List[str], hunks: List[List[str]], path: str) -> List[str]:
    search_start = 0
    for hunk in hunks:
        old_seq = [line[1:] for line in hunk if line[:1] in (" ", "-")]
        new_seq = [line[1:] for line in hunk if line[:1] in (" ", "+")]
        if not old_seq:
            lines[search_start:search_start] = new_seq
            search_start += len(new_seq)
            continue

        match_idx = _find_subsequence(lines, old_seq, search_start)
        if match_idx is None:
            match_idx = _find_subsequence(lines, old_seq, 0)
        if match_idx is None:
            raise GitHubAPIError(f"Patch does not apply to {path}")

        lines[match_idx : match_idx + len(old_seq)] = new_seq
        search_start = match_idx + len(new_seq)
    return lines


def _parse_apply_patch_blocks(patch: str) -> List[Dict[str, Any]]:
    lines = patch.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise GitHubAPIError("Patch missing Begin Patch header")

    blocks: List[Dict[str, Any]] = []
    idx = 1
    while idx < len(lines):
        line = lines[idx]
        if line.strip() == "*** End Patch":
            return blocks
        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            idx += 1
            content_lines: List[str] = []
            while idx < len(lines) and not lines[idx].startswith("*** "):
                patch_line = lines[idx]
                if not patch_line.startswith("+"):
                    raise GitHubAPIError(f"Invalid add-file line in patch for {path}")
                content_lines.append(patch_line[1:])
                idx += 1
            blocks.append({"action": "add", "path": path, "lines": content_lines})
            continue
        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            idx += 1
            blocks.append({"action": "delete", "path": path})
            continue
        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: ") :].strip()
            idx += 1
            move_to = None
            if idx < len(lines) and lines[idx].startswith("*** Move to: "):
                move_to = lines[idx][len("*** Move to: ") :].strip()
                idx += 1

            hunks: List[List[str]] = []
            current_hunk: List[str] = []
            while idx < len(lines) and not lines[idx].startswith("*** "):
                patch_line = lines[idx]
                if patch_line == "*** End of File":
                    idx += 1
                    continue
                if patch_line.startswith("@@"):
                    if current_hunk:
                        hunks.append(current_hunk)
                        current_hunk = []
                    idx += 1
                    continue
                if patch_line[:1] not in (" ", "+", "-"):
                    raise GitHubAPIError(f"Invalid patch line in update for {path}")
                current_hunk.append(patch_line)
                idx += 1
            if current_hunk:
                hunks.append(current_hunk)
            blocks.append({"action": "update", "path": path, "move_to": move_to, "hunks": hunks})
            continue

        raise GitHubAPIError("Unexpected patch content")

    raise GitHubAPIError("Patch missing End Patch footer")


def _apply_tool_patch(repo_dir: str, patch: str) -> None:
    blocks = _parse_apply_patch_blocks(patch)
    for block in blocks:
        action = block["action"]
        if action == "add":
            path = block["path"]
            abs_path = _safe_repo_path(repo_dir, path)
            if os.path.exists(abs_path):
                raise GitHubAPIError(f"File already exists: {path}")
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            content = "\n".join(block["lines"])
            if block["lines"]:
                content += "\n"
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            continue

        if action == "delete":
            path = block["path"]
            abs_path = _safe_repo_path(repo_dir, path)
            if not os.path.exists(abs_path):
                raise GitHubAPIError(f"File does not exist: {path}")
            os.remove(abs_path)
            continue

        if action == "update":
            path = block["path"]
            abs_path = _safe_repo_path(repo_dir, path)
            if not os.path.exists(abs_path):
                raise GitHubAPIError(f"File does not exist: {path}")
            with open(abs_path, "r", encoding="utf-8") as f:
                text = f.read()
            lines, ends_with_newline = _split_text_lines(text)
            hunks = block["hunks"]
            updated_lines = _apply_patch_hunks(lines, hunks, path)
            updated_text = _join_text_lines(updated_lines, ends_with_newline)

            move_to = block.get("move_to")
            if move_to:
                new_abs_path = _safe_repo_path(repo_dir, move_to)
                os.makedirs(os.path.dirname(new_abs_path), exist_ok=True)
                with open(new_abs_path, "w", encoding="utf-8") as f:
                    f.write(updated_text)
                if new_abs_path != abs_path:
                    os.remove(abs_path)
            else:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(updated_text)
            continue

        raise GitHubAPIError("Unsupported patch action")


async def _apply_patch_to_repo(repo_dir: str, patch: str) -> None:
    """Write a unified diff to disk and apply it with ``git apply``."""
    if not patch or not patch.strip():
        raise GitHubAPIError("Received empty patch to apply in workspace")

    if patch.lstrip().startswith("*** Begin Patch"):
        _apply_tool_patch(repo_dir, patch)
        return

    patch = _maybe_unescape_unified_diff(patch)

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

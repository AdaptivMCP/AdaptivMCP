"""Workspace and shell helpers for GitHub MCP tools."""

from __future__ import annotations

import asyncio
import base64
import random
import os
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


def _jitter_sleep_seconds(delay_seconds: float) -> float:
    """Apply jitter to retry sleeps to reduce synchronized git fetch/clone retries."""

    try:
        delay = float(delay_seconds)
    except Exception:
        return 0.0
    if delay <= 0:
        return 0.0

    # Keep tests deterministic.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return delay

    return random.uniform(0.0, delay)


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
            await asyncio.sleep(_jitter_sleep_seconds(delay))
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

    # Ensure bundled ripgrep (vendor/rg) is available as `rg` in workspace shells.
    # This avoids reliance on system packages in provider environments.
    if cwd and os.name != "nt" and sys.platform.startswith("linux"):
        try:
            start_dir = os.path.realpath(cwd)
            candidate = start_dir
            for _ in range(10):
                vendor_dir = os.path.join(candidate, "vendor", "rg", "linux-x64")
                rg_path = os.path.join(vendor_dir, "rg")
                if os.path.isfile(rg_path) and os.access(rg_path, os.X_OK):
                    existing_path = proc_env.get("PATH", "")
                    if vendor_dir not in existing_path.split(os.pathsep):
                        proc_env["PATH"] = vendor_dir + os.pathsep + existing_path
                    break
                parent = os.path.dirname(candidate)
                if parent == candidate:
                    break
                candidate = parent
        except Exception:
            # Never fail the tool due to PATH decoration.
            pass

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

    # Allow a conservative set of characters; replace the rest (no regex).
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    parts: list[str] = []
    prev_underscore = False
    for ch in raw:
        if ch in allowed:
            parts.append(ch)
            prev_underscore = False
        else:
            if not prev_underscore:
                parts.append("_")
                prev_underscore = True
    slug = "".join(parts).strip("._-")
    # Collapse underscore runs (no regex).
    if slug:
        collapsed: list[str] = []
        prev_us = False
        for ch in slug:
            if ch == "_":
                if not prev_us:
                    collapsed.append(ch)
                prev_us = True
            else:
                collapsed.append(ch)
                prev_us = False
        slug = "".join(collapsed).strip("._-")

    if not slug:
        return "main"

    return slug


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
            # Workspace directories are keyed by ref, so callers expect the workspace
            # checked out on ``effective_ref``. Some tools (e.g. shells that create
            # branches) can mutate the checkout inside an existing workspace.
            # When preserving changes we avoid destructive resets, but we still
            # enforce the requested branch when the workspace is clean.
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

            # Ensure we are on the expected branch/ref.
            show_branch = await run_shell(
                "git branch --show-current",
                cwd=workspace_dir,
                timeout_seconds=60,
            )
            current_branch = (show_branch.get("stdout", "") or "").strip() or None
            if current_branch and current_branch != effective_ref:
                status = await run_shell(
                    "git status --porcelain",
                    cwd=workspace_dir,
                    timeout_seconds=60,
                )
                dirty = bool((status.get("stdout", "") or "").strip())
                if dirty:
                    raise GitHubAPIError(
                        "Workspace is on the wrong branch and has local changes. "
                        f"Expected '{effective_ref}', found '{current_branch}'. "
                        "Commit/stash changes or use workspace_self_heal_branch to recover."
                    )

                # Best-effort: check out the requested ref without rewriting history.
                q_ref = shlex.quote(effective_ref)
                checkout = await _run_git_with_retry(
                    run_shell,
                    f"git checkout {q_ref}",
                    cwd=workspace_dir,
                    timeout_seconds=120,
                    env=git_env,
                )
                if checkout.get("exit_code", 0) != 0:
                    # If the local branch is missing, create/reset it from origin.
                    checkout = await _run_git_with_retry(
                        run_shell,
                        f"git checkout -B {q_ref} origin/{q_ref}",
                        cwd=workspace_dir,
                        timeout_seconds=120,
                        env=git_env,
                    )
                    if checkout.get("exit_code", 0) != 0:
                        stderr = checkout.get("stderr", "") or checkout.get("stdout", "")
                        raise GitHubAPIError(
                            "Failed to restore workspace branch checkout. "
                            f"Tried to check out '{effective_ref}'. git error: {stderr}"
                        )

            return workspace_dir

        q_ref = shlex.quote(effective_ref)
        # When not preserving changes, ensure we are on the requested branch/ref and
        # hard-reset to match origin.
        refresh_steps = [
            ("git fetch origin --prune", 300),
            (f"git checkout -B {q_ref} origin/{q_ref}", 120),
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


def _is_hunk_header_with_ranges(line: str) -> bool:
    if not isinstance(line, str):
        return False
    s = line.strip()
    if not (s.startswith("@@") and s.endswith("@@")):
        return False
    # Expected middle like: "@@ -a,b +c,d @@" (commas optional)
    # Tokenize by whitespace.
    parts = s.split()
    if len(parts) < 4:
        return False
    if parts[0] != "@@" or parts[-1] != "@@":
        return False

    def _valid_range(tok: str, prefix: str) -> bool:
        if not tok.startswith(prefix):
            return False
        rest = tok[len(prefix) :]
        if not rest:
            return False
        # allow digits or digits, digits
        nums = rest.split(",", 1)
        if not nums[0].isdigit():
            return False
        if len(nums) == 2 and nums[1] and not nums[1].isdigit():
            return False
        return True

    return _valid_range(parts[1], "-") and _valid_range(parts[2], "+")


def _patch_has_hunk_header_with_ranges(patch: str) -> bool:
    if not patch:
        return False
    for line in patch.splitlines():
        if _is_hunk_header_with_ranges(line):
            return True
    return False


def _looks_like_rangeless_git_patch(patch: str) -> bool:
    """Return True when a patch looks like a git diff but hunks omit ranges.

    Some assistants emit `@@` lines without `-a,b +c,d` ranges. `git apply`
    rejects these with "patch with only garbage". We detect that shape and
    fall back to the internal hunk-applier (which matches by content).
    """

    if not isinstance(patch, str):
        return False

    lines = patch.splitlines()
    in_diff = False
    saw_rangeless_hunk = False
    for line in lines:
        if line.startswith("diff --git "):
            in_diff = True
            continue
        if not in_diff:
            continue
        if line.startswith("@@"):
            if _is_hunk_header_with_ranges(line):
                return False
            saw_rangeless_hunk = True
    return saw_rangeless_hunk


def _parse_rangeless_git_patch(patch: str) -> List[Dict[str, Any]]:
    """Parse a minimal git-style diff that uses bare `@@` hunk separators.

    Supports update diffs (including simple rename via a/b paths).
    """

    lines = patch.splitlines()
    blocks: List[Dict[str, Any]] = []
    idx = 0

    def _parse_diff_header(line: str) -> Optional[tuple[str, str]]:
        if not line.startswith("diff --git "):
            return None
        rest = line[len("diff --git ") :]
        if not rest.startswith("a/"):
            return None
        # split "a/<path> b/<path>"
        try:
            a_part, b_part = rest.split(" b/", 1)
        except ValueError:
            return None
        if not a_part.startswith("a/"):
            return None
        a_path = a_part[len("a/") :]
        b_path = b_part
        if not a_path or not b_path:
            return None
        return a_path, b_path

    while idx < len(lines):
        line = lines[idx]
        parsed = _parse_diff_header(line)
        if not parsed:
            idx += 1
            continue

        a_path, b_path = parsed
        move_to = b_path if a_path != b_path else None
        path = a_path
        idx += 1

        # Skip headers until we reach the file markers.
        while idx < len(lines) and not lines[idx].startswith("--- "):
            if lines[idx].startswith("diff --git "):
                raise GitHubAPIError("Malformed patch: missing file header for diff")
            idx += 1
        if idx >= len(lines) or not lines[idx].startswith("--- "):
            raise GitHubAPIError("Malformed patch: missing --- file header")
        idx += 1
        if idx >= len(lines) or not lines[idx].startswith("+++ "):
            raise GitHubAPIError("Malformed patch: missing +++ file header")
        idx += 1

        hunks: List[List[str]] = []
        current: List[str] = []

        while idx < len(lines) and not lines[idx].startswith("diff --git "):
            pline = lines[idx]
            if pline.startswith("@@"):
                # bare @@ acts as hunk delimiter (no ranges expected here).
                if current:
                    hunks.append(current)
                    current = []
                idx += 1
                continue
            if pline.startswith(r"\ No newline at end of file"):
                idx += 1
                continue
            if pline[:1] in (" ", "+", "-"):
                current.append(pline)
                idx += 1
                continue

            # Ignore common metadata lines (index, mode changes) and blank separators.
            if pline.startswith(
                (
                    "index ",
                    "new file mode",
                    "deleted file mode",
                    "similarity index",
                    "rename from",
                    "rename to",
                )
            ):
                idx += 1
                continue
            if pline.strip() == "":
                # A blank diff line must still carry a prefix (' ', '+', '-').
                raise GitHubAPIError("Malformed patch: blank line without diff prefix")

            raise GitHubAPIError("Malformed patch: unexpected content in diff body")

        if current:
            hunks.append(current)

        if not hunks:
            raise GitHubAPIError("Malformed patch: no hunks found for diff")

        blocks.append({"action": "update", "path": path, "move_to": move_to, "hunks": hunks})

    if not blocks:
        raise GitHubAPIError("Malformed patch: no diffs found")

    return blocks


def _apply_rangeless_git_patch(repo_dir: str, patch: str) -> None:
    blocks = _parse_rangeless_git_patch(patch)
    for block in blocks:
        path = block["path"]
        abs_path = _safe_repo_path(repo_dir, path)
        if not os.path.exists(abs_path):
            raise GitHubAPIError(f"File does not exist: {path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            text = f.read()

        lines, ends_with_newline = _split_text_lines(text)
        updated_lines = _apply_patch_hunks(lines, block["hunks"], path)
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


def _safe_repo_path(repo_dir: str, rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise GitHubAPIError("path must be a non-empty string")
    raw_path = rel_path.strip()
    if os.path.isabs(raw_path):
        candidate = os.path.realpath(raw_path)
    else:
        rel_path = raw_path.lstrip("/\\")
        candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
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
    """Write a unified diff to disk and apply it with ``git apply``.

    This helper supports three patch formats:
    1) The MCP "tool patch" format (*** Begin Patch ...), applied in-process.
    2) Standard git unified diffs (diff --git / --- / +++ / @@ -a,b +c,d @@).
    3) A minimal git-style diff that uses bare `@@` hunk separators (no ranges),
    which some assistants emit. These are applied in-process.
    """

    if not patch or not patch.strip():
        raise GitHubAPIError("Received empty patch to apply in workspace")

    if patch.lstrip().startswith("*** Begin Patch"):
        _apply_tool_patch(repo_dir, patch)
        return

    patch = _maybe_unescape_unified_diff(patch)

    # Fallback for assistant-generated diffs that omit hunk ranges.
    if _looks_like_rangeless_git_patch(patch):
        _apply_rangeless_git_patch(repo_dir, patch)
        return

    if patch and not patch.endswith("\n"):
        patch = patch + "\n"

    # Use a unique temporary file to avoid cross-call interference.
    patch_fd, patch_path = tempfile.mkstemp(prefix="mcp_patch_", suffix=".diff", dir=repo_dir)
    try:
        with os.fdopen(patch_fd, "w", encoding="utf-8") as f:
            f.write(patch)

        apply_result = await _run_shell(
            f"git apply --recount --whitespace=nowarn {shlex.quote(patch_path)}",
            cwd=repo_dir,
            timeout_seconds=max(1, int(config.WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS)),
        )
        if apply_result["exit_code"] != 0:
            stderr = apply_result.get("stderr", "") or apply_result.get("stdout", "")
            lowered = (stderr or "").lower()
            hint = ""
            if (
                "only garbage" in lowered
                and "@@" in patch
                and not _patch_has_hunk_header_with_ranges(patch)
            ):
                hint = (
                    " Patch hunks appear to use bare '@@' separators without line ranges. "
                    "Use a standard unified diff hunk header like '@@ -1,3 +1,3 @@', "
                    "or use the MCP tool patch format ('*** Begin Patch')."
                )
            raise GitHubAPIError(f"git apply failed while preparing workspace: {stderr}{hint}")
    finally:
        try:
            os.remove(patch_path)
        except Exception:
            pass


__all__ = [
    "_apply_patch_to_repo",
    "_clone_repo",
    "_prepare_temp_virtualenv",
    "_run_shell",
    "_workspace_path",
]

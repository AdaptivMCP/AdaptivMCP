"""Repo mirror and shell helpers for GitHub MCP tools."""

from __future__ import annotations

import asyncio
import base64
import os
import shlex
import shutil
import sys
import tempfile
from typing import Any

from . import config
from .exceptions import GitHubAPIError, GitHubAuthError
from .http_clients import _get_github_token
from .utils import _get_main_module


def _is_git_rate_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        marker in lowered
        for marker in ("rate limit", "secondary rate limit", "abuse detection")
    )


def _jitter_sleep_seconds(delay_seconds: float) -> float:
    """Backward-compatible wrapper for shared retry jitter."""

    from .retry_utils import jitter_sleep_seconds

    # Git retry backoff uses "full jitter".
    return jitter_sleep_seconds(delay_seconds, respect_min=False)


async def _run_git_with_retry(
    run_shell,
    cmd: str,
    *,
    cwd: str | None,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
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
    cwd: str | None = None,
    timeout_seconds: int = 0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a shell command with author/committer env vars injected."""
    shell_executable = os.environ.get("SHELL")
    if os.name == "nt":
        shell_executable = shell_executable or shutil.which("bash")

    main_module = _get_main_module()
    proc_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": getattr(
            main_module, "GIT_AUTHOR_NAME", config.GIT_AUTHOR_NAME
        ),
        "GIT_AUTHOR_EMAIL": getattr(
            main_module, "GIT_AUTHOR_EMAIL", config.GIT_AUTHOR_EMAIL
        ),
        "GIT_COMMITTER_NAME": getattr(
            main_module, "GIT_COMMITTER_NAME", config.GIT_COMMITTER_NAME
        ),
        "GIT_COMMITTER_EMAIL": getattr(
            main_module, "GIT_COMMITTER_EMAIL", config.GIT_COMMITTER_EMAIL
        ),
    }
    if env is not None:
        proc_env.update(env)

    # Ensure bundled ripgrep (vendor/rg) is available as `rg` in repo mirror shells.
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
            # Avoid failing the tool due to PATH decoration.
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

    async def _terminate_process() -> None:
        """Best-effort termination for the subprocess and its children.

        Hosted MCP deployments can see upstream disconnects/cancellations.
        Ensure we do not leave runaway subprocesses that can exhaust CPU/memory
        and eventually trigger hangs or server disconnects.
        """

        if os.name != "nt":
            import signal

            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
                return
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
        if timeout_seconds and timeout_seconds > 0:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            timed_out = False
        else:
            stdout_bytes, stderr_bytes = await proc.communicate()
            timed_out = False
    except asyncio.CancelledError:
        # Client disconnects/cancellation: ensure the subprocess does not keep
        # running in the background and consuming resources.
        try:
            await _terminate_process()
        except Exception:
            pass
        raise
    except TimeoutError:
        timed_out = True
        # Best-effort termination: kill the whole process group on POSIX so
        # child processes (e.g. pytest workers) don't keep pipes open.
        try:
            await _terminate_process()
        except Exception:
            pass

        # Best-effort output collection after timeout. Keep configurable.
        try:
            collect_timeout = getattr(config, "ADAPTIV_MCP_TIMEOUT_COLLECT_SECONDS", 0)
            if collect_timeout and int(collect_timeout) > 0:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=int(collect_timeout)
                )
            else:
                stdout_bytes, stderr_bytes = await proc.communicate()
        except Exception as exc:
            # Do not swallow errors while collecting stdout/stderr after a timeout.
            # When communicate() fails (e.g., pipes already closed), return a
            # diagnostic string in stderr so callers can surface meaningful context.
            stdout_bytes = b""
            try:
                stderr_bytes = (
                    f"Failed to collect process output after timeout: {exc.__class__.__name__}: {exc}\n"
                ).encode("utf-8", errors="replace")
            except Exception:
                stderr_bytes = b"Failed to collect process output after timeout.\n"

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


def _append_git_config_env(env: dict[str, str], key: str, value: str) -> None:
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


def _git_auth_env() -> dict[str, str]:
    env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
    try:
        token = _get_github_token()
    except GitHubAuthError:
        return env

    # GitHub supports basic auth with username "x-access-token" and the token as password.
    basic_token = base64.b64encode(f"x-access-token:{token}".encode()).decode("utf-8")
    header_value = f"Authorization: Basic {basic_token}"

    # Correct name (no extra underscore).
    env["GIT_HTTP_EXTRAHEADER"] = header_value

    # Also set via config-env to improve compatibility across git builds.
    _append_git_config_env(env, "http.extraHeader", header_value)

    return env


def _git_env_has_auth_header(env: dict[str, str]) -> bool:
    if env.get("GIT_HTTP_EXTRAHEADER"):
        return True
    for key, value in env.items():
        if key.startswith("GIT_CONFIG_KEY_") and value == "http.extraHeader":
            return True
    return False


def _git_no_auth_env() -> dict[str, str]:
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

    # Best-effort context without dumping huge logs. Exclude environment content.
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

    if not raw.strip():
        return "main"

    return raw.strip()


async def _clone_repo(
    full_name: str, ref: str | None = None, *, preserve_changes: bool = False
) -> str:
    """Clone or return a persistent repo mirror (workspace clone) for ``full_name``/``ref``."""
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
            # Workspace directories are keyed by ref, so callers expect the repo mirror
            # (workspace clone) to be checked out on ``effective_ref``. Some tools
            # (e.g. shells that create branches) can mutate the checkout inside an
            # existing repo mirror. When preserving changes we avoid destructive
            # resets, but we still enforce the requested branch when the repo mirror
            # is clean.
            git_timeout = int(
                getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0) or 0
            )
            fetch_result = await _run_git_with_retry(
                run_shell,
                "git fetch origin --prune",
                cwd=workspace_dir,
                timeout_seconds=git_timeout,
                env=git_env,
            )
            if fetch_result["exit_code"] != 0:
                stderr = fetch_result.get("stderr", "") or fetch_result.get(
                    "stdout", ""
                )
                if _is_git_auth_error(stderr) and _git_env_has_auth_header(git_env):
                    fetch_result = await _run_git_with_retry(
                        run_shell,
                        "git fetch origin --prune",
                        cwd=workspace_dir,
                        timeout_seconds=git_timeout,
                        env=no_auth_env,
                    )
                    if fetch_result["exit_code"] == 0:
                        git_env = no_auth_env
                        return workspace_dir
                    stderr = fetch_result.get("stderr", "") or fetch_result.get(
                        "stdout", ""
                    )
                _raise_git_auth_error("Repo mirror fetch", stderr)
                raise GitHubAPIError(
                    f"Repo mirror fetch failed for {full_name}@{effective_ref}: {stderr}"
                )

            # Ensure we are on the expected branch/ref.
            show_branch = await run_shell(
                "git branch --show-current",
                cwd=workspace_dir,
                timeout_seconds=git_timeout,
            )
            current_branch = (show_branch.get("stdout", "") or "").strip() or None
            if current_branch and current_branch != effective_ref:
                status = await run_shell(
                    "git status --porcelain",
                    cwd=workspace_dir,
                    timeout_seconds=git_timeout,
                )
                dirty = bool((status.get("stdout", "") or "").strip())
                if dirty:
                    raise GitHubAPIError(
                        "Repo mirror is on the wrong branch and has local changes. "
                        f"Expected '{effective_ref}', found '{current_branch}'. "
                        "Commit/stash changes or use workspace_self_heal_branch to recover."
                    )

                # Best-effort: check out the requested ref without rewriting history.
                q_ref = shlex.quote(effective_ref)
                checkout = await _run_git_with_retry(
                    run_shell,
                    f"git checkout {q_ref}",
                    cwd=workspace_dir,
                    timeout_seconds=git_timeout,
                    env=git_env,
                )
                if checkout.get("exit_code", 0) != 0:
                    # If the local branch is missing, create/reset it from origin.
                    checkout = await _run_git_with_retry(
                        run_shell,
                        f"git checkout -B {q_ref} origin/{q_ref}",
                        cwd=workspace_dir,
                        timeout_seconds=git_timeout,
                        env=git_env,
                    )
                    if checkout.get("exit_code", 0) != 0:
                        stderr = checkout.get("stderr", "") or checkout.get(
                            "stdout", ""
                        )
                        raise GitHubAPIError(
                            "Failed to restore workspace branch checkout. "
                            f"Tried to check out '{effective_ref}'. git error: {stderr}"
                        )

            return workspace_dir

        q_ref = shlex.quote(effective_ref)
        # When not preserving changes, ensure we are on the requested branch/ref and
        # hard-reset to match origin.
        git_timeout = int(
            getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0) or 0
        )
        refresh_steps = [
            ("git fetch origin --prune", git_timeout),
            (f"git checkout -B {q_ref} origin/{q_ref}", git_timeout),
            (f"git reset --hard origin/{q_ref}", git_timeout),
            ("git clean -fdx --exclude .venv-mcp", git_timeout),
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
                _raise_git_auth_error("Repo mirror refresh", stderr)
                raise GitHubAPIError(
                    f"Repo mirror refresh failed for {full_name}@{effective_ref}: {stderr}"
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
    git_timeout = int(getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0) or 0)
    result = await _run_git_with_retry(
        run_shell,
        cmd,
        cwd=None,
        timeout_seconds=git_timeout,
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
                timeout_seconds=git_timeout,
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


async def _prepare_temp_virtualenv(repo_dir: str) -> dict[str, str]:
    """Ensure the workspace virtualenv exists and return env vars that activate it.

    Despite the historical name ("temp"), this virtualenv is **persistent** per
    workspace repo mirror: it lives at ``<repo_dir>/.venv-mcp`` and is reused
    across tool calls until explicitly removed.

    Lifecycle:
    - "Start": create/repair the venv as needed (this function).
    - "Use": pass the returned env into :func:`_run_shell`.
    - "Stop": remove the venv via :func:`_stop_workspace_virtualenv`.

    To avoid doing expensive bootstrapping on every call, a small marker file
    is written after the venv is successfully initialized.
    """

    main_module = _get_main_module()
    run_shell = getattr(main_module, "_run_shell", _run_shell)

    venv_dir = os.path.join(repo_dir, ".venv-mcp")
    ready_marker = os.path.join(venv_dir, ".mcp_ready")

    # Per-repo lock so concurrent tool calls don't fight over the venv.
    if not hasattr(_prepare_temp_virtualenv, "_locks"):
        _prepare_temp_virtualenv._locks = {}
    locks: dict[str, asyncio.Lock] = _prepare_temp_virtualenv._locks
    lock = locks.get(repo_dir)
    if lock is None:
        lock = asyncio.Lock()
        locks[repo_dir] = lock

    def _venv_bin_dir() -> str:
        return "Scripts" if os.name == "nt" else "bin"

    def _venv_python_path(venv_root: str) -> str:
        bin_dir = _venv_bin_dir()
        exe = "python.exe" if os.name == "nt" else "python"
        return os.path.join(venv_root, bin_dir, exe)

    def _activation_env(venv_root: str) -> dict[str, str]:
        bin_dir = _venv_bin_dir()
        bin_path = os.path.join(venv_root, bin_dir)
        return {
            "VIRTUAL_ENV": venv_root,
            "PATH": f"{bin_path}{os.pathsep}" + os.environ.get("PATH", ""),
        }

    async def _ensure_pip(venv_root: str) -> None:
        vpy = shlex.quote(_venv_python_path(venv_root))

        # First check whether pip is usable.
        check = await run_shell(
            f"{vpy} -m pip --version",
            cwd=repo_dir,
            timeout_seconds=getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0),
        )
        if check.get("exit_code", 0) == 0:
            # Upgrade tooling for more reliable installs.
            upgrade = await run_shell(
                f"{vpy} -m pip install --upgrade pip setuptools wheel",
                cwd=repo_dir,
                timeout_seconds=getattr(
                    config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0
                ),
            )
            if upgrade.get("exit_code", 0) != 0:
                stderr = upgrade.get("stderr", "") or upgrade.get("stdout", "")
                raise GitHubAPIError(f"Failed to upgrade pip tooling: {stderr}")
            return

        # Attempt to bootstrap pip using ensurepip.
        ensure = await run_shell(
            f"{vpy} -m ensurepip --upgrade",
            cwd=repo_dir,
            timeout_seconds=getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0),
        )
        if ensure.get("exit_code", 0) != 0:
            stderr = ensure.get("stderr", "") or ensure.get("stdout", "")
            raise GitHubAPIError(f"Failed to bootstrap pip via ensurepip: {stderr}")

        # Re-check and upgrade.
        check2 = await run_shell(
            f"{vpy} -m pip --version",
            cwd=repo_dir,
            timeout_seconds=getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0),
        )
        if check2.get("exit_code", 0) != 0:
            stderr = check2.get("stderr", "") or check2.get("stdout", "")
            raise GitHubAPIError(f"pip remains unavailable after ensurepip: {stderr}")

        upgrade2 = await run_shell(
            f"{vpy} -m pip install --upgrade pip setuptools wheel",
            cwd=repo_dir,
            timeout_seconds=getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0),
        )
        if upgrade2.get("exit_code", 0) != 0:
            stderr = upgrade2.get("stderr", "") or upgrade2.get("stdout", "")
            raise GitHubAPIError(f"Failed to upgrade pip tooling: {stderr}")

    async with lock:
        # Fast path: venv is ready.
        if os.path.isdir(venv_dir) and os.path.isfile(_venv_python_path(venv_dir)):
            if os.path.isfile(ready_marker):
                return _activation_env(venv_dir)

            # Legacy venvs (or partially initialized ones) are repaired once.
            try:
                await _ensure_pip(venv_dir)
                os.makedirs(venv_dir, exist_ok=True)
                with open(ready_marker, "w", encoding="utf-8") as handle:
                    handle.write("ok\n")
                return _activation_env(venv_dir)
            except Exception:
                shutil.rmtree(venv_dir, ignore_errors=True)

        # If a venv exists but is partially deleted, remove it.
        if os.path.isdir(venv_dir):
            vpy = _venv_python_path(venv_dir)
            if not os.path.isfile(vpy):
                shutil.rmtree(venv_dir, ignore_errors=True)

        # Create venv. Prefer --upgrade-deps when supported.
        create_cmd = f"{shlex.quote(sys.executable)} -m venv --upgrade-deps {shlex.quote(venv_dir)}"
        result = await run_shell(
            create_cmd,
            cwd=repo_dir,
            timeout_seconds=getattr(config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0),
        )
        if result.get("exit_code", 0) != 0:
            # Fallback for older/stripped venv modules.
            create_cmd2 = (
                f"{shlex.quote(sys.executable)} -m venv {shlex.quote(venv_dir)}"
            )
            result2 = await run_shell(
                create_cmd2,
                cwd=repo_dir,
                timeout_seconds=getattr(
                    config, "ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", 0
                ),
            )
            if result2.get("exit_code", 0) != 0:
                stderr = result2.get("stderr", "") or result2.get("stdout", "")
                raise GitHubAPIError(f"Failed to create workspace virtualenv: {stderr}")

        await _ensure_pip(venv_dir)
        os.makedirs(venv_dir, exist_ok=True)
        with open(ready_marker, "w", encoding="utf-8") as handle:
            handle.write("ok\n")
        return _activation_env(venv_dir)


async def _workspace_virtualenv_status(repo_dir: str) -> dict[str, Any]:
    """Return lightweight status for the workspace virtualenv."""

    venv_dir = os.path.join(repo_dir, ".venv-mcp")
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    python_path = os.path.join(venv_dir, bin_dir, exe)
    return {
        "venv_dir": venv_dir,
        "exists": os.path.isdir(venv_dir),
        "python_exists": os.path.isfile(python_path),
        "ready": os.path.isfile(os.path.join(venv_dir, ".mcp_ready")),
        "python_path": python_path,
    }


async def _stop_workspace_virtualenv(repo_dir: str) -> dict[str, Any]:
    """Remove the workspace virtualenv ("stop" the venv)."""

    venv_dir = os.path.join(repo_dir, ".venv-mcp")

    # Use the same lock map as _prepare_temp_virtualenv to avoid races.
    if not hasattr(_prepare_temp_virtualenv, "_locks"):
        _prepare_temp_virtualenv._locks = {}
    locks: dict[str, asyncio.Lock] = _prepare_temp_virtualenv._locks
    lock = locks.get(repo_dir)
    if lock is None:
        lock = asyncio.Lock()
        locks[repo_dir] = lock

    async with lock:
        existed = os.path.isdir(venv_dir)
        if existed:
            shutil.rmtree(venv_dir, ignore_errors=True)
        return {
            "venv_dir": venv_dir,
            "existed": existed,
            "deleted": existed and not os.path.exists(venv_dir),
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

    Some generators emit `@@` lines without `-a,b +c,d` ranges. `git apply`
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


def _parse_rangeless_git_patch(patch: str) -> list[dict[str, Any]]:
    """Parse a minimal git-style diff that uses bare `@@` hunk separators.

    Supports update diffs (including simple rename via a/b paths).
    """

    lines = patch.splitlines()
    blocks: list[dict[str, Any]] = []
    idx = 0

    def _parse_diff_header(line: str) -> tuple[str, str] | None:
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

        hunks: list[list[str]] = []
        current: list[str] = []

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

        blocks.append(
            {"action": "update", "path": path, "move_to": move_to, "hunks": hunks}
        )

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

        with open(abs_path, encoding="utf-8") as f:
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
    raw_path = rel_path.strip().replace("\\", "/")
    repo_root = os.path.realpath(repo_dir)

    # Prefer treating true absolute paths as absolute only if they resolve inside
    # the repo mirror. If they don't, fall back to interpreting them as
    # repo-relative (common caller intent for "/subdir/file").
    if os.path.isabs(raw_path) or raw_path.startswith("/"):
        candidate_abs = os.path.realpath(raw_path)
        if candidate_abs != repo_root and candidate_abs.startswith(repo_root + os.sep):
            candidate = candidate_abs
        else:
            raw_path = raw_path.lstrip("/")
            if not raw_path:
                raise GitHubAPIError("path must be repository-relative")
            candidate = ""
    else:
        candidate = ""

    if not candidate:
        # Clamp traversal attempts back to repo root to avoid brittle hard-fails
        # from LLM clients that produce "../" paths.
        rel_path = raw_path.lstrip("/\\")
        parts: list[str] = []
        for part in rel_path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        rel_path = "/".join(parts)
        if not rel_path:
            raise GitHubAPIError("path must be repository-relative")
        candidate = os.path.realpath(os.path.join(repo_root, rel_path))

    if candidate == repo_root or not candidate.startswith(repo_root + os.sep):
        raise GitHubAPIError("path must resolve inside the workspace repository")
    return candidate


def _split_text_lines(text: str) -> tuple[list[str], bool]:
    ends_with_newline = text.endswith("\n")
    lines = text.splitlines()
    return lines, ends_with_newline


def _join_text_lines(lines: list[str], ends_with_newline: bool) -> str:
    text = "\n".join(lines)
    if ends_with_newline and (text or lines):
        text = text + "\n"
    return text


def _find_subsequence(lines: list[str], subseq: list[str], start: int) -> int | None:
    if not subseq:
        return start
    max_idx = len(lines) - len(subseq)
    for idx in range(start, max_idx + 1):
        if lines[idx : idx + len(subseq)] == subseq:
            return idx
    return None


def _apply_patch_hunks(
    lines: list[str], hunks: list[list[str]], path: str
) -> list[str]:
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


def _parse_apply_patch_blocks(patch: str) -> list[dict[str, Any]]:
    lines = patch.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise GitHubAPIError("Patch missing Begin Patch header")

    blocks: list[dict[str, Any]] = []
    idx = 1
    while idx < len(lines):
        line = lines[idx]
        if line.strip() == "*** End Patch":
            return blocks
        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            idx += 1
            content_lines: list[str] = []
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

            hunks: list[list[str]] = []
            current_hunk: list[str] = []
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
            blocks.append(
                {"action": "update", "path": path, "move_to": move_to, "hunks": hunks}
            )
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
            with open(abs_path, encoding="utf-8") as f:
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
    which some generators emit. These are applied in-process.
    """

    if not patch or not patch.strip():
        exc = GitHubAPIError("Received empty patch to apply in workspace")
        exc.category = "validation"
        exc.code = "PATCH_EMPTY"
        exc.origin = "workspace_patch"
        raise exc

    if patch.lstrip().startswith("*** Begin Patch"):
        _apply_tool_patch(repo_dir, patch)
        return

    patch = _maybe_unescape_unified_diff(patch)

    # Fallback for generated diffs that omit hunk ranges.
    if _looks_like_rangeless_git_patch(patch):
        _apply_rangeless_git_patch(repo_dir, patch)
        return

    if patch and not patch.endswith("\n"):
        patch = patch + "\n"

    # A unique temporary file avoids cross-call interference.
    patch_fd, patch_path = tempfile.mkstemp(
        prefix="mcp_patch_", suffix=".diff", dir=repo_dir
    )
    try:
        with os.fdopen(patch_fd, "w", encoding="utf-8") as f:
            f.write(patch)

        apply_timeout = int(
            getattr(config, "WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS", 0) or 0
        )
        apply_result = await _run_shell(
            f"git apply --recount --whitespace=nowarn {shlex.quote(patch_path)}",
            cwd=repo_dir,
            timeout_seconds=apply_timeout,
        )
        if apply_result["exit_code"] != 0:
            stderr = apply_result.get("stderr", "") or apply_result.get("stdout", "")
            lowered = (stderr or "").lower()
            hint = ""
            category = "conflict"
            code = "PATCH_APPLY_FAILED"

            # Heuristics to improve categorization for LLM + dev tooling.
            if (
                "only garbage" in lowered
                or "corrupt patch" in lowered
                or "malformed" in lowered
            ):
                category = "validation"
                code = "PATCH_MALFORMED"
            elif "does not exist" in lowered or "no such file" in lowered:
                category = "not_found"
                code = "FILE_NOT_FOUND"
            if (
                "only garbage" in lowered
                and "@@" in patch
                and not _patch_has_hunk_header_with_ranges(patch)
            ):
                hint = (
                    " Patch hunks appear to use bare '@@' separators without line ranges. "
                    "Standard unified diff hunk headers look like '@@ -1,3 +1,3 @@', "
                    "or use the MCP tool patch format ('*** Begin Patch')."
                )
            exc = GitHubAPIError(
                f"git apply failed while preparing workspace: {stderr}"
            )
            exc.category = category
            exc.code = code
            exc.origin = "workspace_patch"
            if hint:
                # Keep hints separate from the main error message so clients can
                # render them without triggering repetition/looping behavior.
                exc.hint = hint.strip()
            raise exc
    finally:
        try:
            os.remove(patch_path)
        except Exception:
            pass


__all__ = [
    "_apply_patch_to_repo",
    "_clone_repo",
    "_prepare_temp_virtualenv",
    "_stop_workspace_virtualenv",
    "_workspace_virtualenv_status",
    "_run_shell",
    "_workspace_path",
]

# Split from github_mcp.tools_workspace (generated).
import hashlib
import inspect
import os
import shlex
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError, UsageError
from github_mcp.server import CONTROLLER_REPO
from github_mcp.utils import _get_main_module, _normalize_timeout_seconds
from github_mcp.workspace import (
    _apply_patch_to_repo,
    _clone_repo,
    _git_auth_env,
    _prepare_temp_virtualenv,
    _run_shell,
    _stop_workspace_virtualenv,
    _workspace_virtualenv_status,
)


def _cmd_invokes_git(cmd: object) -> bool:
    """Return True if a shell command string invokes git anywhere as a command segment.

    This handles composite commands like: "rm -rf x && git clone ...".
    Used only to decide whether to inject git auth env.
    """
    if not isinstance(cmd, str):
        return False
    s = cmd.strip()
    if not s:
        return False

    # Treat newlines as command separators.
    s = s.replace("\n", ";")

    def _segments(value: str) -> list[str]:
        parts = [value]
        for sep in ("&&", "||", ";", "|"):
            next_parts: list[str] = []
            for part in parts:
                if sep in part:
                    next_parts.extend(part.split(sep))
                else:
                    next_parts.append(part)
            parts = next_parts
        return parts

    def _segment_invokes_git(segment: str) -> bool:
        seg = segment.strip()
        if not seg:
            return False
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        if not tokens:
            return False
        idx = 0
        while idx < len(tokens):
            tok = tokens[idx]
            if tok in {"env", "command", "sudo"}:
                idx += 1
                continue
            if "=" in tok and not tok.startswith("-") and tok.find("=") > 0:
                idx += 1
                continue
            break
        if idx >= len(tokens):
            return False
        cmd_token = tokens[idx]
        base = os.path.basename(cmd_token)
        return base in {"git", "git.exe"}

    return any(_segment_invokes_git(segment) for segment in _segments(s))


def _filter_kwargs_for_callable(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return only the kwargs accepted by ``fn``.

    Orchestration tools often accept dynamic argument dicts that should flow
    through to lower-level tools without hardcoding every parameter name.
    This helper makes that safe by filtering to the callable's current
    signature.
    """

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs

    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return kwargs

    allowed = set(sig.parameters.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


_QUALITY_SUITE_DEFAULTS = {
    "test_command": "pytest -q",
    "lint_command": "ruff check .",
    "timeout_seconds": 0,
    "fail_fast": True,
    "developer_defaults": True,
}


def _build_quality_suite_payload(
    *,
    full_name: str,
    ref: str,
    test_command: str = _QUALITY_SUITE_DEFAULTS["test_command"],
    lint_command: str = _QUALITY_SUITE_DEFAULTS["lint_command"],
    timeout_seconds: float = _QUALITY_SUITE_DEFAULTS["timeout_seconds"],
    fail_fast: bool = _QUALITY_SUITE_DEFAULTS["fail_fast"],
    developer_defaults: bool = _QUALITY_SUITE_DEFAULTS["developer_defaults"],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"full_name": full_name, "ref": ref}

    for key, value, default in (
        ("test_command", test_command, _QUALITY_SUITE_DEFAULTS["test_command"]),
        ("lint_command", lint_command, _QUALITY_SUITE_DEFAULTS["lint_command"]),
        ("timeout_seconds", timeout_seconds, _QUALITY_SUITE_DEFAULTS["timeout_seconds"]),
        ("fail_fast", fail_fast, _QUALITY_SUITE_DEFAULTS["fail_fast"]),
        (
            "developer_defaults",
            developer_defaults,
            _QUALITY_SUITE_DEFAULTS["developer_defaults"],
        ),
    ):
        if value != default:
            payload[key] = value

    extra_payload = dict(extra or {})
    extra_payload.pop("full_name", None)
    extra_payload.pop("ref", None)
    payload.update(extra_payload)
    return payload


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _safe_branch_slug(value: str) -> str:
    """Return a conservative branch slug derived from an arbitrary string."""
    raw = (value or "").strip()
    allowed_extra = set("-_/.")
    # Replace any disallowed runs with a single '-'.
    parts: list[str] = []
    prev_dash = False
    for ch in raw:
        if ch.isalnum() or ch in allowed_extra:
            parts.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                parts.append("-")
                prev_dash = True
    cleaned = "".join(parts).strip("-/.")
    if not cleaned:
        cleaned = "branch"
    # Avoid invalid ref sequences.
    cleaned = cleaned.replace("..", "-").replace("@{", "-")
    # Ensure it starts with an allowed character.
    if cleaned and not cleaned[0].isalnum():
        cleaned = f"b{cleaned}"
    return cleaned


async def _run_shell_ok(
    deps: dict[str, Any], cmd: str, *, cwd: str, timeout_seconds: int
) -> dict[str, Any]:
    res = await deps["run_shell"](cmd, cwd=cwd, timeout_seconds=timeout_seconds)
    if res.get("exit_code", 0) != 0:
        exit_code = res.get("exit_code")
        timed_out = bool(res.get("timed_out", False))
        stderr = (res.get("stderr", "") or "").strip()
        stdout = (res.get("stdout", "") or "").strip()
        detail = stderr or stdout
        # Keep error payloads bounded for tool responses.
        if len(detail) > 4000:
            detail = detail[:4000] + "…"
        raise GitHubAPIError(
            f"Command failed (exit_code={exit_code}, timed_out={timed_out}): {cmd}: {detail}"
        )
    return res


def _requirements_hash(requirements_path: str) -> str:
    with open(requirements_path, "rb") as handle:
        payload = handle.read()
    return hashlib.sha256(payload).hexdigest()


def _requirements_marker_path(venv_dir: str, requirements_path: str) -> str:
    filename = os.path.basename(requirements_path)
    return os.path.join(venv_dir, f".deps-{filename}.sha256")


def _should_install_requirements(venv_dir: str, requirements_path: str) -> bool:
    if not os.path.isfile(requirements_path):
        return False

    marker = _requirements_marker_path(venv_dir, requirements_path)
    if not os.path.isfile(marker):
        return True

    current_hash = _requirements_hash(requirements_path)
    with open(marker, encoding="utf-8") as handle:
        recorded_hash = handle.read().strip()
    return current_hash != recorded_hash


def _write_requirements_marker(venv_dir: str, requirements_path: str) -> None:
    os.makedirs(venv_dir, exist_ok=True)
    marker = _requirements_marker_path(venv_dir, requirements_path)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(_requirements_hash(requirements_path) + "\n")


async def _maybe_install_dev_requirements(
    deps: dict[str, Any],
    *,
    repo_dir: str,
    cwd: str,
    env: dict[str, str] | None,
    timeout_seconds: float,
    installing_dependencies: bool,
    use_temp_venv: bool,
    requirements_filename: str = "dev-requirements.txt",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Best-effort install for ``dev-requirements.txt``.

    The workspace tools optionally install development requirements into the
    persistent workspace virtualenv (``.venv-mcp``). This helper centralizes
    that logic so command runners and the explicit venv lifecycle tool behave
    consistently.

    Notes:
    - Installation is skipped unless both ``installing_dependencies`` and
      ``use_temp_venv`` are truthy.
    - The installation command is executed in ``cwd`` so relative requirement
      paths resolve predictably (callers typically pass the repo root).
    """

    install_steps: list[dict[str, Any]] = []
    if not (installing_dependencies and use_temp_venv):
        return None, install_steps

    req_path = os.path.join(repo_dir, requirements_filename)
    venv_dir = os.path.join(repo_dir, ".venv-mcp")
    if not os.path.isfile(req_path):
        install_result: dict[str, Any] | None = {
            "skipped": True,
            "reason": f"{requirements_filename} not found",
        }
        install_steps.append({"command": None, "result": install_result})
        return install_result, install_steps

    if not _should_install_requirements(venv_dir, req_path):
        install_result = {"skipped": True, "reason": "dependencies already satisfied"}
        install_steps.append({"command": None, "result": install_result})
        return install_result, install_steps

    dep_timeout = _normalize_timeout_seconds(
        config.ADAPTIV_MCP_DEP_INSTALL_TIMEOUT_SECONDS,
        timeout_seconds,
    )
    install_cmd = f"python -m pip install -r {shlex.quote(requirements_filename)}"
    install_result = await deps["run_shell"](
        install_cmd,
        cwd=cwd,
        timeout_seconds=dep_timeout,
        env=env,
    )
    install_steps.append({"command": install_cmd, "result": install_result})
    if install_result.get("exit_code", 0) != 0:
        stderr = (install_result.get("stderr") or "").strip()
        stdout = (install_result.get("stdout") or "").strip()
        detail = stderr or stdout
        raise GitHubAPIError(f"Dependency install failed: {detail}")

    _write_requirements_marker(venv_dir, req_path)
    return install_result, install_steps


def _git_state_markers(repo_dir: str) -> dict[str, bool]:
    git_dir = os.path.join(repo_dir, ".git")
    return {
        "merge_in_progress": os.path.exists(os.path.join(git_dir, "MERGE_HEAD")),
        "rebase_in_progress": os.path.isdir(os.path.join(git_dir, "rebase-apply"))
        or os.path.isdir(os.path.join(git_dir, "rebase-merge")),
        "cherry_pick_in_progress": os.path.exists(
            os.path.join(git_dir, "CHERRY_PICK_HEAD")
        ),
        "revert_in_progress": os.path.exists(os.path.join(git_dir, "REVERT_HEAD")),
    }


async def _diagnose_workspace_branch(
    deps: dict[str, Any], *, repo_dir: str, expected_branch: str
) -> dict[str, Any]:
    """Return lightweight diagnostics used to detect a mangled repo mirror."""
    diag: dict[str, Any] = {"expected_branch": expected_branch}
    t_default = _normalize_timeout_seconds(
        config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS,
        0,
    )
    show_branch = await deps["run_shell"](
        "git branch --show-current", cwd=repo_dir, timeout_seconds=t_default
    )
    diag["show_current_exit_code"] = show_branch.get("exit_code")
    diag["current_branch"] = (show_branch.get("stdout", "") or "").strip() or None

    status = await deps["run_shell"](
        "git status --porcelain", cwd=repo_dir, timeout_seconds=t_default
    )
    diag["status_exit_code"] = status.get("exit_code")
    diag["status_is_clean"] = not (status.get("stdout", "") or "").strip()

    conflicted = await deps["run_shell"](
        "git diff --name-only --diff-filter=U", cwd=repo_dir, timeout_seconds=t_default
    )
    conflicted_files = [
        line.strip()
        for line in (conflicted.get("stdout", "") or "").splitlines()
        if line.strip()
    ]
    diag["conflicted_files"] = conflicted_files
    diag["has_conflicts"] = bool(conflicted_files)

    markers = _git_state_markers(repo_dir)
    diag.update(markers)

    detached_or_wrong_branch = diag["current_branch"] != expected_branch
    mangled = (
        detached_or_wrong_branch
        or markers["merge_in_progress"]
        or markers["rebase_in_progress"]
        or markers["cherry_pick_in_progress"]
        or markers["revert_in_progress"]
        or diag["has_conflicts"]
    )
    diag["mangled"] = mangled
    diag["detached_or_wrong_branch"] = detached_or_wrong_branch
    return diag


async def _delete_branch_via_workspace(
    deps: dict[str, Any], *, full_name: str, branch: str
) -> dict[str, Any]:
    """Delete a branch via git push (remote) + best-effort local deletion."""
    default_branch = _tw()._default_branch_for_repo(full_name)
    if branch == default_branch:
        raise GitHubAPIError(f"Refusing to delete default branch {default_branch!r}")

    effective_ref = _tw()._effective_ref_for_repo(full_name, default_branch)
    repo_dir = await deps["clone_repo"](
        full_name, ref=effective_ref, preserve_changes=True
    )
    await deps["run_shell"](
        f"git checkout {shlex.quote(effective_ref)}",
        cwd=repo_dir,
        timeout_seconds=_normalize_timeout_seconds(
            config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0
        ),
    )

    delete_remote = await deps["run_shell"](
        f"git push origin --delete {shlex.quote(branch)}",
        cwd=repo_dir,
        timeout_seconds=_normalize_timeout_seconds(
            config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0
        ),
    )
    if delete_remote.get("exit_code", 0) != 0:
        stderr = delete_remote.get("stderr", "") or delete_remote.get("stdout", "")
        raise GitHubAPIError(f"git push origin --delete failed: {stderr}")

    delete_local = await deps["run_shell"](
        f"git branch -D {shlex.quote(branch)}",
        cwd=repo_dir,
        timeout_seconds=_normalize_timeout_seconds(
            config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0
        ),
    )
    return {
        "default_branch": default_branch,
        "deleted_branch": branch,
        "delete_remote": delete_remote,
        "delete_local": delete_local,
    }


def _workspace_deps() -> dict[str, Any]:
    """
    Return workspace dependencies.

    Important change: wrap run_shell so that any git command automatically
    receives the GitHub auth header env (GIT_HTTP_EXTRAHEADER + config-env),
    enabling `git push`/`git fetch` in non-interactive environments.
    """
    main_module = _get_main_module()
    clone_repo_fn = getattr(main_module, "_clone_repo", _clone_repo)
    base_run_shell = getattr(main_module, "_run_shell", _run_shell)
    prepare_venv_fn = getattr(
        main_module, "_prepare_temp_virtualenv", _prepare_temp_virtualenv
    )
    stop_venv_fn = getattr(
        main_module, "_stop_workspace_virtualenv", _stop_workspace_virtualenv
    )
    venv_status_fn = getattr(
        main_module, "_workspace_virtualenv_status", _workspace_virtualenv_status
    )

    async def run_shell_with_git_auth(
        cmd: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = _normalize_timeout_seconds(
            timeout_seconds,
            config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS,
        )
        merged: dict[str, str] = {}
        if env:
            merged.update(env)

        # Only inject auth for git commands (keeps non-git commands untouched).
        if _cmd_invokes_git(cmd):
            for k, v in _git_auth_env().items():
                merged.setdefault(k, v)

        return await base_run_shell(
            cmd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=(merged if merged else None),
        )

    return {
        "clone_repo": clone_repo_fn,
        "run_shell": run_shell_with_git_auth,
        "prepare_temp_virtualenv": prepare_venv_fn,
        "stop_virtualenv": stop_venv_fn,
        "virtualenv_status": venv_status_fn,
        "apply_patch_to_repo": _apply_patch_to_repo,
    }


def _resolve_full_name(
    full_name: str | None, *, owner: str | None = None, repo: str | None = None
) -> str:
    """Resolve a repository identifier.

    Canonical identifier is `full_name` ("owner/repo").

    For backwards compatibility, some internal tool wrappers still pass legacy
    alias parameters (owner, repo). Those are accepted here to avoid runtime
    failures even though the external tool schema prefers `full_name`.
    """

    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()

    owner_val = owner.strip() if isinstance(owner, str) else ""
    repo_val = repo.strip() if isinstance(repo, str) else ""

    # Back-compat: allow callers to provide owner+repo instead of full_name.
    if owner_val or repo_val:
        if not owner_val or not repo_val:
            raise UsageError(
                "Provide both 'owner' and 'repo' together, or use 'full_name' as 'owner/repo'."
            )
        return owner_val + "/" + repo_val

    return CONTROLLER_REPO


def _resolve_ref(ref: str, *, branch: str | None = None) -> str:
    """Return the git ref to operate on.

    Canonical selector is `ref`.

    For backwards compatibility, some tool wrappers still pass a legacy `branch`
    alias. If provided, it takes precedence over `ref`.
    """

    if isinstance(branch, str) and branch.strip():
        return branch.strip()
    return ref

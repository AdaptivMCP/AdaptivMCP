from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest

from github_mcp import workspace
from github_mcp.exceptions import GitHubAPIError


@dataclass
class _Call:
    cmd: str
    env: dict[str, str] | None


@pytest.mark.anyio
async def test_clone_repo_preserve_changes_auth_fallback_on_fetch(
    tmp_path, monkeypatch
):
    """When fetch fails with auth-like stderr, retry with no-auth env and return."""

    monkeypatch.setenv("GITHUB_TOKEN", "token-123")

    repo_dir = tmp_path / "repo"
    (repo_dir / ".git").mkdir(parents=True)

    # Make _workspace_path deterministic.
    monkeypatch.setattr(workspace, "_workspace_path", lambda _f, _r: str(repo_dir))

    # Ensure effective ref is exactly the input ref.
    def _effective_ref_for_repo(_full_name: str, ref: str | None) -> str:
        assert ref is not None
        return ref

    monkeypatch.setattr(
        "github_mcp.utils._effective_ref_for_repo",
        _effective_ref_for_repo,
        raising=False,
    )

    ensure_remote_calls: list[dict[str, Any]] = []

    async def fake_ensure_repo_remote(
        run_shell: Callable[..., Any],
        repo_dir_arg: str,
        full_name: str,
        *,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> None:
        ensure_remote_calls.append(
            {
                "repo_dir": repo_dir_arg,
                "full_name": full_name,
                "timeout_seconds": timeout_seconds,
                "env": env,
            }
        )

    monkeypatch.setattr(workspace, "_ensure_repo_remote", fake_ensure_repo_remote)

    calls: list[_Call] = []

    async def fake_run_git_with_retry(
        _run_shell: Callable[..., Any],
        cmd: str,
        *,
        cwd: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append(_Call(cmd=cmd, env=env))
        if cmd == "git fetch origin --prune":
            # First call with auth env fails in an auth-looking way.
            if env and env.get("GIT_HTTP_EXTRAHEADER"):
                return {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "fatal: Authentication failed for https://github.com/x/y.git",
                }
            # Retry with no-auth env succeeds.
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}
        raise AssertionError(f"Unexpected git command: {cmd}")

    monkeypatch.setattr(workspace, "_run_git_with_retry", fake_run_git_with_retry)

    # Minimal run_shell for branch/show-current path isn't needed because we return
    # early after a successful no-auth fetch.
    async def fake_run_shell(*_args, **_kwargs) -> dict[str, Any]:
        raise AssertionError("run_shell should not be called in this scenario")

    class _Main:
        _run_shell = staticmethod(fake_run_shell)

    monkeypatch.setattr(workspace, "_get_main_module", lambda: _Main)

    result_dir = await workspace._clone_repo(
        "octo-org/octo-repo", ref="main", preserve_changes=True
    )

    assert result_dir == str(repo_dir)
    assert ensure_remote_calls, "expected origin remote to be ensured"

    # We should have attempted fetch twice: auth env then no-auth env.
    assert [c.cmd for c in calls] == [
        "git fetch origin --prune",
        "git fetch origin --prune",
    ]
    assert calls[0].env and calls[0].env.get("GIT_HTTP_EXTRAHEADER")
    assert calls[1].env == {"GIT_TERMINAL_PROMPT": "0"}


@pytest.mark.anyio
async def test_clone_repo_preserve_changes_wrong_branch_dirty_raises(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    (repo_dir / ".git").mkdir(parents=True)

    monkeypatch.setattr(workspace, "_workspace_path", lambda _f, _r: str(repo_dir))

    def _effective_ref_for_repo(_full_name: str, ref: str | None) -> str:
        assert ref is not None
        return ref

    monkeypatch.setattr(
        "github_mcp.utils._effective_ref_for_repo",
        _effective_ref_for_repo,
        raising=False,
    )

    async def fake_ensure_repo_remote(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(workspace, "_ensure_repo_remote", fake_ensure_repo_remote)

    async def fake_run_git_with_retry(*_args, **_kwargs) -> dict[str, Any]:
        # Fetch succeeds.
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(workspace, "_run_git_with_retry", fake_run_git_with_retry)

    async def fake_run_shell(
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if command == "git branch --show-current":
            return {"exit_code": 0, "stdout": "other\n", "stderr": ""}
        if command == "git status --porcelain":
            return {"exit_code": 0, "stdout": " M file.txt\n", "stderr": ""}
        raise AssertionError(f"Unexpected shell command: {command}")

    class _Main:
        _run_shell = staticmethod(fake_run_shell)

    monkeypatch.setattr(workspace, "_get_main_module", lambda: _Main)

    with pytest.raises(GitHubAPIError, match=r"wrong branch and has local changes"):
        await workspace._clone_repo(
            "octo-org/octo-repo", ref="main", preserve_changes=True
        )


@pytest.mark.anyio
async def test_clone_repo_preserve_changes_wrong_branch_clean_checkout_fallback(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    (repo_dir / ".git").mkdir(parents=True)

    monkeypatch.setattr(workspace, "_workspace_path", lambda _f, _r: str(repo_dir))

    def _effective_ref_for_repo(_full_name: str, ref: str | None) -> str:
        assert ref is not None
        return ref

    monkeypatch.setattr(
        "github_mcp.utils._effective_ref_for_repo",
        _effective_ref_for_repo,
        raising=False,
    )

    async def fake_ensure_repo_remote(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(workspace, "_ensure_repo_remote", fake_ensure_repo_remote)

    git_calls: list[str] = []

    async def fake_run_git_with_retry(
        _run_shell: Callable[..., Any],
        cmd: str,
        *,
        cwd: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        git_calls.append(cmd)
        if cmd == "git fetch origin --prune":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git checkout -B"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git checkout "):
            # First checkout attempt fails, forcing -B fallback.
            return {"exit_code": 1, "stdout": "", "stderr": "pathspec did not match"}
        raise AssertionError(f"Unexpected git command: {cmd}")

    monkeypatch.setattr(workspace, "_run_git_with_retry", fake_run_git_with_retry)

    async def fake_run_shell(
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if command == "git branch --show-current":
            return {"exit_code": 0, "stdout": "other\n", "stderr": ""}
        if command == "git status --porcelain":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected shell command: {command}")

    class _Main:
        _run_shell = staticmethod(fake_run_shell)

    monkeypatch.setattr(workspace, "_get_main_module", lambda: _Main)

    res = await workspace._clone_repo(
        "octo-org/octo-repo", ref="main", preserve_changes=True
    )
    assert res == str(repo_dir)

    assert git_calls[0] == "git fetch origin --prune"
    assert git_calls[1].startswith("git checkout ")
    assert git_calls[2].startswith("git checkout -B")

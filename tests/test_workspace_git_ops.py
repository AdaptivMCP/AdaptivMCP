from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

import github_mcp.workspace_tools.git_ops as git_ops


@dataclass
class _FakeDeps:
    repo_dir: str = "/tmp/repo"
    run_shell_calls: list[dict[str, Any]] = field(default_factory=list)
    clone_calls: list[tuple[str, str, bool]] = field(default_factory=list)

    async def clone_repo(
        self, full_name: str, *, ref: str, preserve_changes: bool
    ) -> str:
        self.clone_calls.append((full_name, ref, preserve_changes))
        return self.repo_dir

    async def run_shell(
        self, cmd: str, *, cwd: str, timeout_seconds: int | float | None = None
    ):
        self.run_shell_calls.append(
            {"cmd": cmd, "cwd": cwd, "timeout_seconds": timeout_seconds}
        )
        # Default: success with empty output.
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}


@dataclass
class _FakeTW:
    deps: _FakeDeps

    def _workspace_deps(self) -> dict[str, Any]:
        return {"clone_repo": self.deps.clone_repo, "run_shell": self.deps.run_shell}

    def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
        _ = full_name
        return ref

    def _default_branch_for_repo(self, _full_name: str) -> str:
        return "main"


def _seq_provider(values: list[dict[str, Any]]) -> Callable[..., Any]:
    async def _next(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if not values:
            raise AssertionError("snapshot sequence exhausted")
        return values.pop(0)

    return _next


def test_slim_shell_result_trims_and_handles_non_dict() -> None:
    assert git_ops._slim_shell_result("x") == {"raw": "x"}
    long = "a" * 5000
    res = git_ops._slim_shell_result({"exit_code": 1, "stdout": long, "stderr": long})
    assert res["exit_code"] == 1
    assert res["stdout"].endswith("…")
    assert len(res["stdout"]) == 4001
    assert res["stderr"].endswith("…")


def test_shell_error_formats_message_and_trims_detail() -> None:
    err = git_ops._shell_error("action", "boom")
    assert "action failed" in str(err)

    long = "x" * 5000
    err2 = git_ops._shell_error(
        "git cmd",
        {"exit_code": 2, "timed_out": True, "stderr": long, "stdout": ""},
    )
    msg = str(err2)
    assert "exit_code=2" in msg
    assert "timed_out=True" in msg
    assert msg.endswith("…")


def test_parse_git_numstat_parses_text_and_binary() -> None:
    stdout = "1\t2\tfile.txt\n-\t-\tbin.dat\nX\tY\tweird\n1\t2\n\n"
    parsed = git_ops._parse_git_numstat(stdout)
    assert parsed[0] == {
        "path": "file.txt",
        "added": 1,
        "removed": 2,
        "is_binary": False,
    }
    assert parsed[1]["path"] == "bin.dat"
    assert parsed[1]["added"] is None and parsed[1]["removed"] is None
    assert parsed[1]["is_binary"] is True
    # Malformed numeric line is still included with None counts.
    assert parsed[2]["path"] == "weird"
    assert parsed[2]["added"] is None and parsed[2]["removed"] is None


@pytest.mark.anyio
async def test_workspace_sync_to_remote_refuses_without_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)

    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    before = {
        "remote_ref": "origin/main",
        "is_clean": False,
        "ahead": 0,
        "behind": 0,
    }
    monkeypatch.setattr(git_ops, "_workspace_sync_snapshot", _seq_provider([before]))

    res = await git_ops.workspace_sync_to_remote(
        "o/r", ref="main", discard_local_changes=False
    )
    assert res["status"] == "error"
    assert "discard_local_changes" in (res.get("error") or "")
    assert deps.run_shell_calls == []


@pytest.mark.anyio
async def test_workspace_sync_to_remote_forced_calls_reset_and_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)

    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    calls: list[str] = []

    async def _ok(_deps: dict[str, Any], cmd: str, *, cwd: str, timeout_seconds: Any):
        calls.append(cmd)
        assert cwd == deps.repo_dir
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(git_ops, "_run_shell_ok", _ok)

    before = {
        "remote_ref": "origin/main",
        "is_clean": False,
        "ahead": 2,
        "behind": 0,
    }
    after = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 0,
        "behind": 0,
    }
    monkeypatch.setattr(
        git_ops, "_workspace_sync_snapshot", _seq_provider([before, after])
    )

    res = await git_ops.workspace_sync_to_remote(
        "o/r", ref="main", discard_local_changes=True
    )
    assert res["discard_local_changes"] is True
    assert "git reset --hard" in calls[0]
    assert calls[1] == "git clean -fd"


@pytest.mark.anyio
async def test_workspace_sync_bidirectional_diverged_requires_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)
    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    before = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 1,
        "behind": 1,
    }
    monkeypatch.setattr(git_ops, "_workspace_sync_snapshot", _seq_provider([before]))

    res = await git_ops.workspace_sync_bidirectional(
        "o/r", ref="main", discard_local_changes=False
    )
    assert res["status"] == "error"
    assert "diverged" in (res.get("error") or "")


@pytest.mark.anyio
async def test_workspace_sync_bidirectional_fast_forward_from_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)
    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    calls: list[str] = []

    async def _ok(_deps: dict[str, Any], cmd: str, *, cwd: str, timeout_seconds: Any):
        calls.append(cmd)
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(git_ops, "_run_shell_ok", _ok)

    before = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 0,
        "behind": 2,
    }
    after = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 0,
        "behind": 0,
    }
    monkeypatch.setattr(
        git_ops, "_workspace_sync_snapshot", _seq_provider([before, after])
    )

    res = await git_ops.workspace_sync_bidirectional("o/r", ref="main", push=False)
    assert res.get("status") != "error"
    assert res.get("error") is None
    assert "fast_forward_from_remote" in res["actions"]
    assert calls and calls[0].startswith("git reset --hard")


@pytest.mark.anyio
async def test_workspace_sync_bidirectional_commit_then_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)
    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    # Snapshots: before (dirty), after commit (ahead), after push (clean+synced)
    before = {
        "remote_ref": "origin/main",
        "is_clean": False,
        "ahead": 0,
        "behind": 0,
    }
    after_commit = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 1,
        "behind": 0,
    }
    after_push = {
        "remote_ref": "origin/main",
        "is_clean": True,
        "ahead": 0,
        "behind": 0,
    }
    monkeypatch.setattr(
        git_ops,
        "_workspace_sync_snapshot",
        _seq_provider([before, after_commit, after_push]),
    )

    # run_shell should see git add, status, commit, push
    async def _run_shell(cmd: str, *, cwd: str, timeout_seconds: Any):
        assert cwd == deps.repo_dir
        if cmd == "git add -A":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "stdout": " M file.txt\n", "stderr": ""}
        if cmd.startswith("git commit -m"):
            return {"exit_code": 0, "stdout": "[main abc] msg\n", "stderr": ""}
        if cmd.startswith("git push origin"):
            return {"exit_code": 0, "stdout": "pushed\n", "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(deps, "run_shell", _run_shell)

    res = await git_ops.workspace_sync_bidirectional(
        "o/r", ref="main", commit_message="msg", add_all=True, push=True
    )
    assert res.get("status") != "error"
    assert res.get("error") is None
    assert "committed_local_changes" in res["actions"]
    assert "pushed_to_remote" in res["actions"]


@pytest.mark.anyio
async def test_workspace_sync_bidirectional_push_quotes_effective_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)
    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)
    monkeypatch.setattr(git_ops, "_resolve_ref", lambda ref, **_: ref)

    malicious_ref = "main;echo pwned"
    before = {
        "remote_ref": f"origin/{malicious_ref}",
        "is_clean": True,
        "ahead": 1,
        "behind": 0,
    }
    after = {
        "remote_ref": f"origin/{malicious_ref}",
        "is_clean": True,
        "ahead": 0,
        "behind": 0,
    }
    monkeypatch.setattr(git_ops, "_workspace_sync_snapshot", _seq_provider([before, after]))

    seen: list[str] = []

    async def _run_shell(cmd: str, *, cwd: str, timeout_seconds: Any):
        seen.append(cmd)
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(deps, "run_shell", _run_shell)

    res = await git_ops.workspace_sync_bidirectional(
        "o/r", ref=malicious_ref, push=True, add_all=False
    )
    assert res.get("status") != "error"
    push_cmds = [c for c in seen if c.startswith("git push origin")]
    assert len(push_cmds) == 1
    assert "HEAD:'" in push_cmds[0]
    assert ";echo pwned" in push_cmds[0]


@pytest.mark.anyio
async def test_workspace_delete_branch_checkout_failure_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _FakeDeps()
    tw = _FakeTW(deps)
    monkeypatch.setattr(git_ops, "_tw", lambda: tw)
    monkeypatch.setattr(git_ops, "_resolve_full_name", lambda full_name, **_: full_name)

    seen: list[str] = []

    async def _run_shell(cmd: str, *, cwd: str, timeout_seconds: Any):
        seen.append(cmd)
        if cmd.startswith("git checkout"):
            return {"exit_code": 1, "stdout": "", "stderr": "nope"}
        raise AssertionError("unexpected git command after failed checkout")

    monkeypatch.setattr(deps, "run_shell", _run_shell)

    res = await git_ops.workspace_delete_branch("o/r", branch="feature")
    assert res["status"] == "error"
    assert "git checkout" in (res.get("error") or "")
    assert seen and seen[0].startswith("git checkout")

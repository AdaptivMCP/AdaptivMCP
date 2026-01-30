from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from github_mcp.workspace_tools import pr as pr_tool


@dataclass
class _FakeTW:
    quality_result: dict[str, Any] | None = None
    commit_result: dict[str, Any] | None = None
    pr_result: dict[str, Any] | None = None

    effective_calls: list[tuple[str, str]] = field(default_factory=list)
    quality_calls: list[dict[str, Any]] = field(default_factory=list)
    commit_calls: list[dict[str, Any]] = field(default_factory=list)

    def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
        self.effective_calls.append((full_name, ref))
        return f"eff:{ref}"

    async def run_quality_suite(self, **payload: Any) -> dict[str, Any]:
        self.quality_calls.append(payload)
        return dict(self.quality_result or {"status": "ok"})

    async def commit_workspace(self, **payload: Any) -> dict[str, Any]:
        self.commit_calls.append(payload)
        return dict(self.commit_result or {"ok": True, "commit": "abc"})


@pytest.mark.anyio
async def test_commit_and_open_pr_success_without_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTW(pr_result={"status": "ok", "pr_url": "u", "pr_number": 7})

    # pr_tool imports open_pr_for_existing_branch inside the function.
    import github_mcp.main_tools.pull_requests as pr_main

    async def _fake_open_pr_for_existing_branch(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["branch"] == "eff:feature"
        assert kwargs["base"] == "eff:main"
        # Default title uses the effective refs.
        assert kwargs["title"] == "eff:feature -> eff:main"
        return dict(fake.pr_result or {})

    monkeypatch.setattr(pr_tool, "_tw", lambda: fake)
    monkeypatch.setattr(pr_tool, "_build_quality_suite_payload", lambda **k: k)
    monkeypatch.setattr(
        pr_main, "open_pr_for_existing_branch", _fake_open_pr_for_existing_branch
    )

    result = await pr_tool.commit_and_open_pr_from_workspace(
        full_name="o/r",
        ref="feature",
        base="main",
        run_quality=False,
        commit_message="msg",
    )

    assert result["status"] == "ok"
    assert result["branch"] == "eff:feature"
    assert result["base"] == "eff:main"
    assert result["quality"] is None
    assert result["commit"]["commit"] == "abc"
    assert result["pr"]["pr_number"] == 7
    assert result["pr_url"] == "u"
    assert result["pr_number"] == 7

    assert fake.quality_calls == []
    assert fake.commit_calls and fake.commit_calls[0]["push"] is True
    assert fake.commit_calls[0]["add_all"] is True
    assert fake.commit_calls[0]["message"] == "msg"


@pytest.mark.anyio
async def test_commit_and_open_pr_quality_suite_failure_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTW(quality_result={"status": "failed", "ok": False})

    import github_mcp.main_tools.pull_requests as pr_main

    async def _should_not_be_called(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("PR should not be opened when quality fails")

    monkeypatch.setattr(pr_tool, "_tw", lambda: fake)
    monkeypatch.setattr(pr_tool, "_build_quality_suite_payload", lambda **k: k)
    monkeypatch.setattr(pr_main, "open_pr_for_existing_branch", _should_not_be_called)

    result = await pr_tool.commit_and_open_pr_from_workspace(
        full_name="o/r",
        ref="feature",
        base="main",
        run_quality=True,
        quality_timeout_seconds=1,
    )

    assert result["status"] == "error"
    assert result["reason"] == "quality_suite_failed"
    assert result["ref"] == "eff:feature"
    assert result["base"] == "eff:main"
    assert "not committed" in result["message"]
    assert fake.commit_calls == []


@pytest.mark.anyio
async def test_commit_and_open_pr_commit_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTW(commit_result={"error": "nothing to commit"})

    import github_mcp.main_tools.pull_requests as pr_main

    async def _should_not_be_called(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("PR should not be opened when commit fails")

    monkeypatch.setattr(pr_tool, "_tw", lambda: fake)
    monkeypatch.setattr(pr_tool, "_build_quality_suite_payload", lambda **k: k)
    monkeypatch.setattr(pr_main, "open_pr_for_existing_branch", _should_not_be_called)

    result = await pr_tool.commit_and_open_pr_from_workspace(
        full_name="o/r",
        ref="feature",
        base="main",
        run_quality=False,
    )

    assert result["status"] == "error"
    assert result["reason"] == "commit_failed"
    assert result["branch"] == "eff:feature"
    assert result["base"] == "eff:main"
    assert result["commit"]["error"] == "nothing to commit"


@pytest.mark.anyio
async def test_commit_and_open_pr_pr_open_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTW(pr_result={"status": "error", "error": "nope"})

    import github_mcp.main_tools.pull_requests as pr_main

    async def _fake_open_pr_for_existing_branch(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["title"] == "Custom Title"
        return dict(fake.pr_result or {})

    monkeypatch.setattr(pr_tool, "_tw", lambda: fake)
    monkeypatch.setattr(pr_tool, "_build_quality_suite_payload", lambda **k: k)
    monkeypatch.setattr(
        pr_main, "open_pr_for_existing_branch", _fake_open_pr_for_existing_branch
    )

    result = await pr_tool.commit_and_open_pr_from_workspace(
        full_name="o/r",
        ref="feature",
        base="main",
        title="Custom Title",
        run_quality=False,
    )

    assert result["status"] == "error"
    assert result["reason"] == "pr_open_failed"
    assert result["branch"] == "eff:feature"
    assert result["base"] == "eff:main"
    assert result["pr"]["status"] == "error"


@pytest.mark.anyio
async def test_commit_and_open_pr_wraps_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(pr_tool, "_tw", _raise)

    result = await pr_tool.commit_and_open_pr_from_workspace(
        full_name="o/r",
        ref="feature",
        base="main",
    )

    assert result["status"] == "error"
    assert result["ok"] is False
    assert result.get("context") == "commit_and_open_pr_from_workspace"
    assert "unexpected" in result.get("error", "")


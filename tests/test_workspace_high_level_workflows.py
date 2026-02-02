from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    """Minimal stub for github_mcp.tools_workspace used by workflow tests."""

    class uuid:
        @staticmethod
        def uuid4():
            class _U:
                hex = "0123456789abcdef0123456789abcdef"

            return _U()

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    async def workspace_sync_to_remote(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "workspace_sync_to_remote", "kwargs": kwargs})
        return {"status": "success"}

    async def workspace_create_branch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "workspace_create_branch", "kwargs": kwargs})
        return {"ok": True, "new_branch": kwargs.get("new_branch")}

    async def apply_workspace_operations(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "apply_workspace_operations", "kwargs": kwargs})
        return {"status": "ok", "ok": True}

    async def run_quality_suite(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "run_quality_suite", "kwargs": kwargs})
        return {"status": "success"}

    async def commit_and_open_pr_from_workspace(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "commit_and_open_pr_from_workspace", "kwargs": kwargs})
        return {
            "status": "ok",
            "pr_url": "https://example.invalid/pull/1",
            "pr_number": 1,
        }


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Update docs",
        run_quality=True,
        sync_args={"discard_local_changes": False},
        create_branch_args={"push": False},
        apply_ops_args={"preview_only": True},
        quality_args={"developer_defaults": False, "auto_fix": True},
        pr_args={"draft": True},
    )

    assert res["status"] == "ok"
    assert res["base_ref"] == "main"
    assert res["pr_url"] == "https://example.invalid/pull/1"
    assert isinstance(res.get("steps"), list)

    fns = [c["fn"] for c in fake.calls]
    assert fns == [
        "workspace_sync_to_remote",
        "workspace_create_branch",
        "apply_workspace_operations",
        "run_quality_suite",
        "commit_and_open_pr_from_workspace",
    ]

    # Dynamic args were passed through.
    assert fake.calls[0]["kwargs"]["discard_local_changes"] is False
    assert fake.calls[1]["kwargs"]["push"] is False
    assert fake.calls[2]["kwargs"]["preview_only"] is True
    assert fake.calls[3]["kwargs"]["developer_defaults"] is False
    assert fake.calls[3]["kwargs"]["auto_fix"] is True
    assert fake.calls[4]["kwargs"]["draft"] is True


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_skips_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Update docs",
        run_quality=False,
    )

    assert res["status"] == "ok"
    fns = [c["fn"] for c in fake.calls]
    assert "run_quality_suite" not in fns


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_reuses_feature_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        feature_ref="feature/already-exists",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Update docs",
        run_quality=False,
    )

    assert res["status"] == "ok"
    fns = [c["fn"] for c in fake.calls]
    # base sync + feature sync (reuse), then operations + finalize
    assert fns == [
        "workspace_sync_to_remote",
        "workspace_sync_to_remote",
        "apply_workspace_operations",
        "commit_and_open_pr_from_workspace",
    ]

    assert fake.calls[0]["kwargs"]["ref"] == "main"
    assert fake.calls[1]["kwargs"]["ref"] == "feature/already-exists"


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_feature_ref_missing_remote_falls_back_to_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    class _MissingRemote(_FakeTW):
        async def workspace_sync_to_remote(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"fn": "workspace_sync_to_remote", "kwargs": kwargs})
            if kwargs.get("ref") == "feature/missing":
                return {
                    "status": "error",
                    "error": "fatal: ambiguous argument 'origin/feature/missing': unknown revision",
                }
            return {"status": "success"}

    fake = _MissingRemote()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        feature_ref="feature/missing",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Update docs",
        run_quality=False,
    )

    assert res["status"] == "ok"
    fns = [c["fn"] for c in fake.calls]
    # base sync, attempted feature sync (missing), then create branch fallback
    assert fns == [
        "workspace_sync_to_remote",
        "workspace_sync_to_remote",
        "workspace_create_branch",
        "apply_workspace_operations",
        "commit_and_open_pr_from_workspace",
    ]


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_validates_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[],
    )

    assert res["status"] == "error"
    assert res.get("error_detail", {}).get("category") == "validation"
    assert fake.calls == []


@pytest.mark.anyio
async def test_workspace_apply_ops_and_open_pr_quality_failure_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    class _FailQuality(_FakeTW):
        async def run_quality_suite(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"fn": "run_quality_suite", "kwargs": kwargs})
            return {"status": "failed"}

    fake = _FailQuality()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_apply_ops_and_open_pr(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Update docs",
        run_quality=True,
    )

    assert res["status"] == "error"
    assert res.get("reason") == "quality_suite_failed"
    fns = [c["fn"] for c in fake.calls]
    assert "commit_and_open_pr_from_workspace" not in fns

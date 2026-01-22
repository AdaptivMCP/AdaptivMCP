from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    """Stub for github_mcp.tools_workspace used by task workflow tests."""

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

    async def scan_workspace_tree(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "scan_workspace_tree", "kwargs": kwargs})
        # Keep it tiny; callers only need a dict.
        return {"status": "ok", "files": [{"path": "README.md", "size": 1}]}

    async def rg_search_workspace(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "rg_search_workspace", "kwargs": kwargs})
        return {"status": "success", "matches": [{"path": "README.md", "line": 1, "text": "hello"}]}

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

    async def workspace_change_report(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "workspace_change_report", "kwargs": kwargs})
        return {"status": "ok", "base_ref": kwargs.get("base_ref"), "head_ref": kwargs.get("head_ref")}

    async def build_pr_summary(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "build_pr_summary", "kwargs": kwargs})
        return {"status": "ok", "summary": "stub"}

    async def commit_and_open_pr_from_workspace(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "commit_and_open_pr_from_workspace", "kwargs": kwargs})
        return {"status": "ok", "pr_url": "https://example.invalid/pull/123", "pr_number": 123}

    async def commit_workspace(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "commit_workspace", "kwargs": kwargs})
        return {"branch": kwargs.get("ref"), "commit_sha": "deadbeef"}


@pytest.mark.anyio
async def test_workspace_task_plan_collects_tree_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import task_workflows

    fake = _FakeTW()
    monkeypatch.setattr(task_workflows, "_tw", lambda: fake)

    res = await task_workflows.workspace_task_plan(
        full_name="octo-org/octo-repo",
        ref="main",
        queries=["TODO"],
        max_tree_files=10,
        max_tree_bytes=1000,
        max_search_results=5,
    )

    assert res["status"] == "ok"
    assert res["ok"] is True
    assert res["ref"] == "main"
    assert isinstance(res.get("tree"), dict)
    assert isinstance(res.get("searches"), list)
    assert res["searches"][0]["query"] == "TODO"
    fns = [c["fn"] for c in fake.calls]
    assert fns == ["scan_workspace_tree", "rg_search_workspace"]


@pytest.mark.anyio
async def test_workspace_task_apply_edits_passes_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import task_workflows

    fake = _FakeTW()
    monkeypatch.setattr(task_workflows, "_tw", lambda: fake)

    res = await task_workflows.workspace_task_apply_edits(
        full_name="octo-org/octo-repo",
        ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        preview_only=True,
    )

    assert res["status"] == "ok"
    assert res["ok"] is True
    assert [c["fn"] for c in fake.calls] == ["apply_workspace_operations"]
    kwargs = fake.calls[0]["kwargs"]
    assert kwargs["fail_fast"] is True
    assert kwargs["rollback_on_error"] is True
    assert kwargs["preview_only"] is True


@pytest.mark.anyio
async def test_workspace_task_execute_pr_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import task_workflows

    fake = _FakeTW()
    monkeypatch.setattr(task_workflows, "_tw", lambda: fake)

    res = await task_workflows.workspace_task_execute(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Do thing",
        plan_queries=["README"],
        finalize_mode="pr",
        draft=True,
    )

    assert res["status"] == "ok"
    assert res["ok"] is True
    assert res["finalize_mode"] == "pr"
    assert res["finalize"]["pr_number"] == 123

    fns = [c["fn"] for c in fake.calls]
    assert fns == [
        "rg_search_workspace",
        "workspace_sync_to_remote",
        "workspace_create_branch",
        "apply_workspace_operations",
        "run_quality_suite",
        "workspace_change_report",
        "build_pr_summary",
        "commit_and_open_pr_from_workspace",
    ]


@pytest.mark.anyio
async def test_workspace_task_execute_commit_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import task_workflows

    fake = _FakeTW()
    monkeypatch.setattr(task_workflows, "_tw", lambda: fake)

    res = await task_workflows.workspace_task_execute(
        full_name="octo-org/octo-repo",
        base_ref="main",
        operations=[{"op": "write", "path": "README.md", "content": "x"}],
        commit_message="Do thing",
        finalize_mode="commit_only",
    )

    assert res["status"] == "ok"
    assert res["finalize_mode"] == "commit_only"
    assert res["finalize"].get("commit_sha") == "deadbeef"
    fns = [c["fn"] for c in fake.calls]
    assert "commit_workspace" in fns
    assert "commit_and_open_pr_from_workspace" not in fns


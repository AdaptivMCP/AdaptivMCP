import asyncio

import pytest

import github_mcp.mcp_server.context as context


def test_task_workflows_summarizers():
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")

    from github_mcp.workspace_tools import task_workflows

    tree = {
        "full_name": "org/repo",
        "ref": "main",
        "path": "",
        "cursor": 0,
        "next_cursor": None,
        "max_entries": 10,
        "max_depth": 1,
        "include_hidden": True,
        "include_dirs": True,
        "results": [
            {"type": "file", "path": "a.py"},
            {"type": "dir", "path": "pkg"},
            {"type": "file", "path": "b.py"},
            "not-a-dict",
        ],
        "truncated": False,
    }

    summary = task_workflows._summarize_tree(tree)
    assert summary is not None
    assert summary["file_count"] == 2
    assert summary["dir_count"] == 1
    assert summary["result_count"] == 4

    search = {
        "query": "needle",
        "path": "",
        "engine": "rg",
        "max_results": 50,
        "context_lines": 2,
        "matches": [
            {"path": "a.py", "line": 1, "text": "needle"},
            {"path": "a.py", "line": 2, "text": "needle"},
            {"path": "b.py", "line": 3, "text": "needle"},
            "not-a-dict",
        ],
        "truncated": False,
    }

    ssum = task_workflows._summarize_search_result(search)
    assert ssum is not None
    assert ssum["match_count"] == 4
    assert ssum["file_count"] == 2

    ops = {
        "ref": "main",
        "status": "ok",
        "ok": False,
        "preview_only": False,
        "results": [
            {"status": "ok"},
            {"status": "error"},
            {"status": "ok"},
            "not-a-dict",
        ],
    }

    osum = task_workflows._summarize_operations_result(ops)
    assert osum is not None
    assert osum["operation_count"] == 4
    assert osum["ok_count"] == 2
    assert osum["error_count"] == 1


def test_workspace_task_plan_ok(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")

    from github_mcp.workspace_tools import task_workflows

    class FakeTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
            return ref

        async def scan_workspace_tree(self, **kwargs):
            return {
                "full_name": kwargs.get("full_name"),
                "ref": kwargs.get("ref"),
                "path": "",
                "results": [
                    {"type": "file", "path": "a.py"},
                    {"type": "dir", "path": "pkg"},
                ],
            }

        async def rg_search_workspace(self, **kwargs):
            return {
                "query": kwargs.get("query"),
                "path": kwargs.get("path"),
                "engine": "rg",
                "max_results": kwargs.get("max_results"),
                "context_lines": kwargs.get("context_lines"),
                "matches": [
                    {"path": "a.py", "line": 1, "text": "hit"},
                    {"path": "b.py", "line": 2, "text": "hit"},
                ],
            }

    monkeypatch.setattr(task_workflows, "_tw", lambda: FakeTW())

    result = asyncio.run(
        task_workflows.workspace_task_plan(
            full_name="org/repo",
            ref="main",
            queries=["hit"],
            include_details=True,
            include_steps=True,
        )
    )

    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["tree_summary"]["file_count"] == 1
    assert result["tree_summary"]["dir_count"] == 1
    assert result["search_summaries"][0]["query"] == "hit"
    assert result["search_summaries"][0]["summary"]["file_count"] == 2
    assert "tree" in result
    assert "searches" in result
    assert "steps" in result


def test_workspace_task_plan_validation_error(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")

    from github_mcp.workspace_tools import task_workflows

    class FakeTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
            return ref

    monkeypatch.setattr(task_workflows, "_tw", lambda: FakeTW())

    # queries must be list[str]
    result = asyncio.run(
        task_workflows.workspace_task_plan(
            full_name="org/repo",
            ref="main",
            queries="nope",  # type: ignore[arg-type]
        )
    )

    assert result["status"] == "error"
    assert result["ok"] is False


def test_workspace_task_apply_edits_paths(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")

    from github_mcp.workspace_tools import task_workflows

    class FakeTW:
        def __init__(self, result):
            self._result = result

        def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
            return ref

        async def apply_workspace_operations(self, **kwargs):
            return self._result

    ops = [{"op": "mkdir", "path": "x"}]

    monkeypatch.setattr(task_workflows, "_tw", lambda: FakeTW({"status": "error"}))
    res = asyncio.run(
        task_workflows.workspace_task_apply_edits(
            full_name="org/repo",
            ref="main",
            operations=ops,
            include_steps=True,
        )
    )
    assert res["status"] == "error"
    assert res["reason"] == "apply_edits_failed"
    assert "steps" in res

    monkeypatch.setattr(
        task_workflows,
        "_tw",
        lambda: FakeTW(
            {"status": "ok", "ok": False, "results": [{"status": "error"}]}
        ),
    )
    res = asyncio.run(
        task_workflows.workspace_task_apply_edits(
            full_name="org/repo",
            ref="main",
            operations=ops,
        )
    )
    assert res["status"] == "error"
    assert res["reason"] == "apply_edits_partial"

    monkeypatch.setattr(
        task_workflows,
        "_tw",
        lambda: FakeTW({"status": "ok", "ok": True, "results": [{"status": "ok"}]}),
    )
    res = asyncio.run(
        task_workflows.workspace_task_apply_edits(
            full_name="org/repo",
            ref="main",
            operations=ops,
            include_details=True,
        )
    )
    assert res["status"] == "ok"
    assert res["ok"] is True
    assert res["operations_summary"]["ok_count"] == 1
    assert "operations" in res

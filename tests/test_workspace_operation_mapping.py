from __future__ import annotations

from typing import Any

import pytest


def test_normalize_workspace_operation_accepts_operation_key_and_aliases() -> None:
    from github_mcp.workspace_tools import fs

    # operation -> op and rm -> delete
    op = fs._normalize_workspace_operation({"operation": "rm", "path": "a.txt"})
    assert op["op"] == "delete"
    assert op["path"] == "a.txt"

    # mv -> move
    op = fs._normalize_workspace_operation({"op": "mv", "src": "a", "dst": "b"})
    assert op["op"] == "move"

    # mkdirp -> mkdir + parents=True
    op = fs._normalize_workspace_operation({"op": "mkdirp", "path": "dir"})
    assert op["op"] == "mkdir"
    assert op.get("parents") is True


def test_apply_workspace_operations_write_action_resolver_treats_read_alias_as_read_only() -> None:
    from github_mcp.workspace_tools.fs import _apply_workspace_operations_write_action_resolver

    # Alias via `operation` key.
    args = {"operations": [{"operation": "read", "path": "README.md", "start_line": 1}]}
    assert _apply_workspace_operations_write_action_resolver(args) is False


@pytest.mark.anyio
async def test_workspace_manage_folders_detects_conflicting_paths() -> None:
    from github_mcp.workspace_tools.workflows import workspace_manage_folders_and_open_pr

    res = await workspace_manage_folders_and_open_pr(
        full_name="octo-org/octo-repo",
        create_paths=["a", "b"],
        delete_paths=["b"],
        # Prevent downstream network/workspace actions from being invoked.
        run_quality=False,
        sync_base_to_remote=False,
    )

    assert isinstance(res, dict)
    assert res.get("status") == "error"
    assert res.get("ok") is False
    assert "both created and deleted" in (res.get("error") or "").lower()


@pytest.mark.anyio
async def test_workspace_batch_maps_top_level_operations_to_apply_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import batch

    calls: list[dict[str, Any]] = []

    async def fake_apply_workspace_operations(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"status": "ok", "ok": True, "result": []}

    monkeypatch.setattr(batch, "apply_workspace_operations", fake_apply_workspace_operations)

    res = await batch.workspace_batch(
        full_name="octo-org/octo-repo",
        plans=[
            {
                "ref": "main",
                # Shorthand: ops at top-level.
                "ops": [{"op": "rm", "path": "a.txt", "allow_missing": True}],
            }
        ],
    )

    assert isinstance(res, dict)
    assert res.get("status") in {"ok", "success"}
    assert calls, "expected apply_workspace_operations to be called"
    op_list = calls[0].get("operations")
    assert isinstance(op_list, list) and op_list
    assert op_list[0]["op"] == "delete"  # rm alias normalized


@pytest.mark.anyio
async def test_workspace_batch_accepts_apply_ops_ops_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import batch

    calls: list[dict[str, Any]] = []

    async def fake_apply_workspace_operations(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"status": "ok", "ok": True, "result": []}

    monkeypatch.setattr(batch, "apply_workspace_operations", fake_apply_workspace_operations)

    res = await batch.workspace_batch(
        full_name="octo-org/octo-repo",
        plans=[
            {
                "ref": "main",
                "apply_ops": {"ops": [{"op": "mv", "src": "a", "dst": "b"}]},
            }
        ],
    )

    assert isinstance(res, dict)
    assert res.get("status") in {"ok", "success"}
    assert calls, "expected apply_workspace_operations to be called"
    op_list = calls[0].get("operations")
    assert isinstance(op_list, list) and op_list
    assert op_list[0]["op"] == "move"  # mv alias normalized


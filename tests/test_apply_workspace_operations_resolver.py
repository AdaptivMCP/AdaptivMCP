from __future__ import annotations

from github_mcp.workspace_tools.fs import _apply_workspace_operations_write_action_resolver


def test_apply_workspace_operations_resolver_preview_only_is_read() -> None:
    assert _apply_workspace_operations_write_action_resolver({"preview_only": True, "operations": []}) is False


def test_apply_workspace_operations_resolver_read_sections_only_is_read() -> None:
    args = {
        "preview_only": False,
        "operations": [
            {"op": "read_sections", "path": "README.md", "start_line": 1},
            {"op": "read_sections", "path": "README.md", "start_line": 50},
        ],
    }
    assert _apply_workspace_operations_write_action_resolver(args) is False


def test_apply_workspace_operations_resolver_mixed_ops_is_write() -> None:
    args = {
        "preview_only": False,
        "operations": [
            {"op": "read_sections", "path": "README.md", "start_line": 1},
            {"op": "replace_text", "path": "README.md", "old": "a", "new": "b"},
        ],
    }
    assert _apply_workspace_operations_write_action_resolver(args) is True

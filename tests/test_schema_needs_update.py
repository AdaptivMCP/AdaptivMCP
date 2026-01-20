from __future__ import annotations

from github_mcp.mcp_server.decorators import _schema_needs_update


def test_schema_needs_update_detects_non_required_differences() -> None:
    # Historically we only updated when desired introduced newly-required params.
    # Schemas should also refresh when type/default metadata changes.
    existing = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
        "additionalProperties": True,
    }
    desired = {
        "type": "object",
        "properties": {"x": {"type": "string", "default": "hello"}},
        "required": ["x"],
        "additionalProperties": True,
    }
    assert _schema_needs_update(existing, desired)

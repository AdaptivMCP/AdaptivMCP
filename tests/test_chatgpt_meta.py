import types

from github_mcp.http_routes.actions_compat import serialize_actions_for_compatibility
from github_mcp.mcp_server import decorators, schemas


def test_register_with_fastmcp_adds_chatgpt_meta():
    original_registry = list(decorators._REGISTERED_MCP_TOOLS)

    try:
        @decorators.mcp_tool(name="sample_tool", write_action=False, description="test tool")
        def _sample_tool() -> None:
            return None

        tool_obj = decorators._REGISTERED_MCP_TOOLS[-1][0]

        vis = tool_obj.meta["chatgpt.com/visibility"]
        assert isinstance(vis, str)
        assert vis.startswith("schema:sample_tool:")
        assert len(vis.split(":")[-1]) == 10
        assert (
            tool_obj.meta["chatgpt.com/toolInvocation/invoking"]
            == decorators.OPENAI_INVOKING_MESSAGE
        )
        assert (
            tool_obj.meta["chatgpt.com/toolInvocation/invoked"]
            == decorators.OPENAI_INVOKED_MESSAGE
        )
        assert tool_obj.meta["chatgpt.com/title"] == "Sample Tool"
    finally:
        decorators._REGISTERED_MCP_TOOLS[:] = original_registry


def test_actions_compat_prefers_chatgpt_title():
    tool = types.SimpleNamespace(
        name="demo_tool",
        description="demo description",
        annotations=None,
        meta={"chatgpt.com/title": "ChatGPT Name"},
        title=None,
    )

    class _Server:
        _REGISTERED_MCP_TOOLS = [(tool, None)]

        @staticmethod
        def _normalize_input_schema(_tool):
            return None

    actions = serialize_actions_for_compatibility(_Server())
    assert actions[0]["display_name"] == "ChatGPT Name"
    assert actions[0]["title"] == "ChatGPT Name"


def test_register_with_fastmcp_surfaces_schema_and_write_gate():
    original_registry = list(decorators._REGISTERED_MCP_TOOLS)

    try:

        @decorators.mcp_tool(name="schema_test_tool", write_action=False, description="demo")
        def _schema_test_tool(example: int, note: str | None = None) -> None:
            return None

        tool_obj = decorators._REGISTERED_MCP_TOOLS[-1][0]
        schema_meta = tool_obj.meta["chatgpt.com/input_schema"]

        assert schema_meta["type"] == "object"
        assert schema_meta["properties"]["example"]["type"] == "integer"
        assert tool_obj.meta["write_allowed"] == decorators.WRITE_ALLOWED
    finally:
        decorators._REGISTERED_MCP_TOOLS[:] = original_registry


def test_normalize_input_schema_tightens_required_properties():
    tool = types.SimpleNamespace(
        name="list_repositories",
        inputSchema={"type": "object", "required": ["full_name"], "properties": {}},
    )

    schema = schemas._normalize_input_schema(tool)

    assert schema["type"] == "object"
    assert schema["properties"]["full_name"]["type"] == "string"
    assert "full_name" in schema["required"]


def test_sanitize_metadata_value_handles_unserializable_types():
    payload = {
        "token": "https://x-access-token:abc123@github.com/",
        "set_data": {1, 2},
        "custom": object(),
    }

    sanitized = schemas._sanitize_metadata_value(payload)

    assert sanitized["token"] == "https://x-access-token:***@github.com/"
    assert isinstance(sanitized["set_data"], list)
    assert isinstance(sanitized["custom"], str)

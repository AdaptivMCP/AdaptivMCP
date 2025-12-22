import types

from github_mcp.http_routes.actions_compat import serialize_actions_for_compatibility
from github_mcp.mcp_server import decorators


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

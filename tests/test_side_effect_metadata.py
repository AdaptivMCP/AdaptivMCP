import github_mcp.server as server
from github_mcp.mcp_server.decorators import refresh_registered_tool_metadata
from github_mcp.main_tools import introspection
from github_mcp import config
from github_mcp.mcp_server.context import _record_recent_tool_event



def _tool_entry(name: str, write_allowed: bool):
    original = server.WRITE_ALLOWED
    try:
        server.WRITE_ALLOWED = write_allowed
        refresh_registered_tool_metadata(write_allowed)
        catalog = introspection.list_all_actions(include_parameters=False, compact=True)
        tools = {tool["name"]: tool for tool in catalog["tools"]}

        # Attach FastMCP meta so we can regression-test connector-facing keys
        from github_mcp.main_tools._main import _main
        m = _main()
        tool_obj = None
        for t, _f in m._REGISTERED_MCP_TOOLS:
            if (getattr(t, "name", None) or getattr(_f, "__name__", None)) == name:
                tool_obj = t
                break
        if tool_obj is not None:
            tools[name]["meta"] = dict(getattr(tool_obj, "meta", {}) or {})
            tools[name]["annotations"] = getattr(tool_obj, "annotations", None)
        return tools[name]
    finally:
        server.WRITE_ALLOWED = original
        refresh_registered_tool_metadata(original)



def test_local_mutations_do_not_prompt_regardless_of_write_gate():
    open_tool = _tool_entry("run_command", True)
    gated_tool = _tool_entry("run_command", False)

    assert open_tool["write_action"] is False
    assert gated_tool["write_action"] is False

    # Domain-prefixed metadata must also reflect non-prompting local mutation tools



def test_remote_mutation_always_requires_approval():
    enabled = _tool_entry("create_file", True)
    disabled = _tool_entry("create_file", False)

    assert enabled["write_action"] is True
    assert disabled["write_action"] is True
    assert enabled["side_effects"] == disabled["side_effects"] == "REMOTE_MUTATION"

    # Domain-prefixed metadata must reflect prompting write tools
    # Remote mutation should not claim readOnlyHint



def test_write_gate_does_not_turn_local_tools_into_prompting_writes():
    local = _tool_entry("run_command", False)
    remote = _tool_entry("create_file", False)

    assert local["write_action"] is False
    assert remote["write_action"] is True



def test_owner_logs_and_events_are_unmodified():
    secret = "ghp_" + "a" * 30
    config.ERROR_LOG_HANDLER.records.clear()

    if hasattr(server.RECENT_TOOL_EVENTS, "clear"):
        server.RECENT_TOOL_EVENTS.clear()
    else:
        while server.RECENT_TOOL_EVENTS:
            server.RECENT_TOOL_EVENTS.pop()

    config.BASE_LOGGER.error("leaked secret %s", secret)

    assert any(secret in (rec.get("message") or "") for rec in config.ERROR_LOG_HANDLER.records)

    _record_recent_tool_event({"message": "token: " + secret})
    last_event = server.RECENT_TOOL_EVENTS[-1]
    assert secret in str(last_event)

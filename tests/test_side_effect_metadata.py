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
        return tools[name]
    finally:
        server.WRITE_ALLOWED = original
        refresh_registered_tool_metadata(original)


def test_tool_metadata_flips_with_write_gate():
    open_tool = _tool_entry("run_command", True)
    gated_tool = _tool_entry("run_command", False)

    assert open_tool["write_action"] is False
    assert gated_tool["write_action"] is True
    assert open_tool["side_effects"] == gated_tool["side_effects"] == "LOCAL_MUTATION"


def test_remote_mutation_always_requires_approval():
    enabled = _tool_entry("create_file", True)
    disabled = _tool_entry("create_file", False)

    assert enabled["write_action"] is True
    assert disabled["write_action"] is True
    assert enabled["side_effects"] == disabled["side_effects"] == "REMOTE_MUTATION"


def test_all_mutations_gate_when_disabled():
    local = _tool_entry("run_command", False)
    remote = _tool_entry("create_file", False)

    assert local["write_action"] is True
    assert remote["write_action"] is True


def test_redaction_covers_logs_and_events():
    secret = "ghp_" + "a" * 30
    config.ERROR_LOG_HANDLER.records.clear()

    if hasattr(server.RECENT_TOOL_EVENTS, "clear"):
        server.RECENT_TOOL_EVENTS.clear()
    else:
        while server.RECENT_TOOL_EVENTS:
            server.RECENT_TOOL_EVENTS.pop()

    config.BASE_LOGGER.error("leaked secret %s", secret)

    assert all(secret not in (rec.get("message") or "") for rec in config.ERROR_LOG_HANDLER.records)

    _record_recent_tool_event({"message": f"token: {secret}"})
    last_event = server.RECENT_TOOL_EVENTS[-1]
    assert secret not in str(last_event)

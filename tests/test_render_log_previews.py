def test_log_preflight_preserves_full_strings() -> None:
    from github_mcp.mcp_server.schemas import _preflight_tool_args

    payload = _preflight_tool_args("tool", {"s": "x" * 200}, compact=True)
    assert payload["args"]["s"] == "x" * 200

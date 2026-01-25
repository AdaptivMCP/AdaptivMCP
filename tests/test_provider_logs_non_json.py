def test_truncate_text_does_not_json_dump_mappings():
    from github_mcp.mcp_server import decorators

    s = decorators._truncate_text({"b": 2, "a": 1})
    assert "a=1" in s
    assert "b=2" in s
    assert "{" not in s

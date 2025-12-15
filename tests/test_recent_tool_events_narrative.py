def test_get_recent_tool_events_includes_narrative_and_transcript(monkeypatch):
    import main
    from github_mcp import server

    # Reset in-memory ring buffer.
    server.RECENT_TOOL_EVENTS.clear()

    server.RECENT_TOOL_EVENTS.append(
        {
            "ts": 1.0,
            "event": "tool_recent_start",
            "tool_name": "run_command",
            "repo": "owner/repo",
            "ref": "main",
            "user_message": "Starting run_command (read) on owner/repo@main.",
        }
    )
    server.RECENT_TOOL_EVENTS.append(
        {
            "ts": 2.0,
            "event": "tool_recent_ok",
            "tool_name": "run_command",
            "repo": "owner/repo",
            "ref": "main",
            "duration_ms": 12,
            "user_message": "Finished run_command on owner/repo@main in 12ms.",
        }
    )

    res = main.get_recent_tool_events(limit=10, include_success=True)

    assert "narrative" in res
    assert "transcript" in res
    assert any("Starting run_command" in msg for msg in res["narrative"])
    assert any("Finished run_command" in msg for msg in res["narrative"])
    assert "Starting run_command" in res["transcript"]
    assert "Finished run_command" in res["transcript"]

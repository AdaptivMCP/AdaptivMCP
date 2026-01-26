from __future__ import annotations

from github_mcp.workspace_tools import commands


def test_compact_command_payload_drops_redundant_fields() -> None:
    payload = {
        "command": "ls -la",
        "command_input": "ls -la",
        "command_lines": ["ls -la"],
    }

    cleaned = commands._compact_command_payload(
        payload,
        command_lines_out=["ls -la"],
    )

    assert "command_input" not in cleaned
    assert "command_lines" not in cleaned


def test_compact_command_payload_keeps_multiline_command_lines() -> None:
    payload = {
        "command": "echo one\necho two",
        "command_input": "echo one\necho two",
        "command_lines": ["echo one", "echo two"],
    }

    cleaned = commands._compact_command_payload(
        payload,
        command_lines_out=["echo one", "echo two"],
    )

    assert "command_input" not in cleaned
    assert cleaned["command_lines"] == ["echo one", "echo two"]

from github_mcp.mcp_server.privacy import strip_location_metadata


def test_strip_location_metadata_removes_location_and_timezone_keys() -> None:
    meta = {
        "openai/userLocation": {"city": "Example", "country": "EX"},
        "timezone_offset_minutes": 300,
        "title": "Example Tool",
        "openai/toolInvocation/invoking": "ignored",
    }

    sanitized = strip_location_metadata(meta)

    assert "openai/userLocation" not in sanitized
    assert "timezone_offset_minutes" not in sanitized
    # Non-location metadata is preserved.
    assert sanitized["title"] == "Example Tool"
    assert "openai/toolInvocation/invoking" in sanitized

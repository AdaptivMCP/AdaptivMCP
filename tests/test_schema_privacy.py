import types

from github_mcp.mcp_server import schemas


def test_strip_location_from_schema_removes_location_fields():
    raw = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "location": {"type": "string"},
            "ip_address": {"type": "string"},
            "metadata": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string"},
                    "clientIp": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["timezone", "clientIp"],
            },
        },
        "required": ["location", "query", "ip_address"],
    }

    cleaned = schemas._strip_location_from_schema(raw)

    assert "location" not in cleaned["properties"]
    assert "ip_address" not in cleaned["properties"]
    assert "timezone" not in cleaned["properties"]["metadata"]["properties"]
    assert "clientIp" not in cleaned["properties"]["metadata"]["properties"]
    assert cleaned["required"] == ["query"]
    assert cleaned["properties"]["metadata"]["required"] == []


def test_normalize_input_schema_always_returns_schema():
    class DummyTool:
        name = "dummy_tool"
        inputSchema = {
            "type": "object",
            "properties": {
                "location_hint": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["location_hint"],
        }

    tool = types.SimpleNamespace(**DummyTool.__dict__)

    result = schemas._normalize_input_schema(tool)

    assert result["type"] == "object"
    assert result["properties"] == {"query": {"type": "string"}}
    assert result["required"] == []


def test_normalize_input_schema_prefers_parameters_attribute():
    class DummyTool:
        name = "dummy_tool"
        parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["query"],
        }

    tool = types.SimpleNamespace(**DummyTool.__dict__)

    result = schemas._normalize_input_schema(tool)

    assert result["type"] == "object"
    assert set(result["properties"]) == {"query"}
    assert result["required"] == ["query"]

import pytest

from github_mcp.mcp_server import decorators as dec
from github_mcp.mcp_server.errors import ToolInputValidationError


def test_token_like_values_are_rejected():
    with pytest.raises(ToolInputValidationError) as excinfo:
        dec._ensure_no_tokenlike_inputs(
            "example_tool",
            {"note": "ghp_1234567890abcdef1234"},
        )

    assert "Token-like strings detected" in str(excinfo.value)
    assert excinfo.value.field == "note"


def test_nested_token_like_inputs_include_path():
    with pytest.raises(ToolInputValidationError) as excinfo:
        dec._ensure_no_tokenlike_inputs(
            "example_tool",
            {"payload": {"secrets": ["ok", "sk-abc123def456ghi789"]}},
        )

    assert "payload → secrets → 1" in (excinfo.value.field or "")


def test_clean_inputs_pass_validation():
    dec._ensure_no_tokenlike_inputs(
        "example_tool",
        {"note": "hello", "payload": {"secrets": ["ok", "fine"]}},
    )

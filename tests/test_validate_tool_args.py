import pytest

import main


@pytest.mark.asyncio
async def test_validate_tool_args_passes_for_known_tool():
    result = await main.validate_tool_args(
        "compare_refs", {"full_name": "owner/repo", "base": "main", "head": "feature"}
    )

    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_validate_tool_args_reports_missing_fields():
    result = await main.validate_tool_args(
        "compare_refs", {"full_name": "owner/repo", "base": "main"}
    )

    assert result["valid"] is False
    assert any("head" in error.get("message", "") for error in result["errors"])


@pytest.mark.asyncio
async def test_validate_tool_args_unknown_tool_raises():
    with pytest.raises(ValueError):
        await main.validate_tool_args("missing_tool", {})

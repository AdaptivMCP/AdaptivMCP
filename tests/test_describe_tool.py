import pytest

import main


@pytest.mark.asyncio
async def test_describe_tool_returns_single_tool_with_schema():
    result = await main.describe_tool("run_tests")

    assert result["name"] == "run_tests"
    assert result.get("input_schema") is not None
    assert result["input_schema"].get("type") == "object"
    assert "properties" in result["input_schema"]


@pytest.mark.asyncio
async def test_describe_tool_without_parameters_omits_input_schema():
    result = await main.describe_tool("run_tests", include_parameters=False)

    assert result["name"] == "run_tests"
    assert "input_schema" not in result


@pytest.mark.asyncio
async def test_describe_tool_unknown_name_raises_value_error():
    with pytest.raises(ValueError):
        await main.describe_tool("__definitely_not_a_real_tool__")

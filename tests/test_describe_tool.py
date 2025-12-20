import json

import main
import pytest


@pytest.mark.asyncio
async def test_describe_tool_returns_single_tool_with_schema():
    result = await main.describe_tool("run_tests")

    assert result["name"] == "run_tests"
    assert result.get("input_schema") is not None
    assert result["input_schema"].get("type") == "object"
    assert "properties" in result["input_schema"]
    # Multi-tool API always includes a tools list with at least one entry.
    assert isinstance(result.get("tools"), list)
    assert any(entry.get("name") == "run_tests" for entry in result["tools"])


@pytest.mark.asyncio
async def test_describe_tool_strips_internal_meta_fields():
    result = await main.describe_tool("get_server_config")

    serialized = json.dumps(result)

    assert "\"_meta\"" not in serialized


@pytest.mark.asyncio
async def test_describe_tool_without_parameters_omits_input_schema():
    result = await main.describe_tool("run_tests", include_parameters=False)

    assert result["name"] == "run_tests"
    assert "input_schema" not in result


@pytest.mark.asyncio
async def test_describe_tool_unknown_name_raises_value_error():
    with pytest.raises(ValueError):
        await main.describe_tool("__definitely_not_a_real_tool__")


@pytest.mark.asyncio
async def test_describe_tool_supports_multiple_names():
    result = await main.describe_tool(names=["run_tests", "list_all_actions"])

    tools = result["tools"]
    tool_names = [tool["name"] for tool in tools]

    assert "run_tests" in tool_names
    assert "list_all_actions" in tool_names
    # The first tool should still mirror the legacy top-level shape.
    assert result["name"] == tools[0]["name"]


@pytest.mark.asyncio
async def test_describe_tool_mixed_known_and_unknown_includes_missing():
    unknown_name = "__definitely_not_a_real_tool_for_batch__"
    result = await main.describe_tool(names=["run_tests", unknown_name])

    assert "run_tests" in [tool["name"] for tool in result["tools"]]
    assert unknown_name in result.get("missing_tools", [])


@pytest.mark.asyncio
async def test_describe_tool_rejects_more_than_ten_tools():
    catalog = main.list_all_actions(include_parameters=False, compact=True)
    tool_names = [tool["name"] for tool in catalog["tools"]][:11]

    if len(tool_names) < 11:
        pytest.skip("Not enough tools registered to exercise 10+ limit")

    with pytest.raises(ValueError):
        await main.describe_tool(names=tool_names)

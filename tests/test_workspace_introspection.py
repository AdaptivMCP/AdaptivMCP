import pytest

import main


@pytest.mark.asyncio
async def test_workspace_tools_are_auto_approved_and_have_schemas():
    workspace_tools = [
        "workspace_create_branch",
        "workspace_delete_branch",
        "workspace_self_heal_branch",
    ]

    described = await main.describe_tool(names=workspace_tools)
    described_by_name = {entry["name"]: entry for entry in described["tools"]}

    catalog = main.list_all_actions(include_parameters=True, compact=False)
    catalog_by_name = {entry["name"]: entry for entry in catalog["tools"]}

    for tool_name in workspace_tools:
        for source, mapping in (
            ("describe_tool", described_by_name),
            ("list_all_actions", catalog_by_name),
        ):
            assert tool_name in mapping, f"{tool_name} missing from {source}"
            entry = mapping[tool_name]
            assert entry.get("write_action") is True
            assert entry.get("auto_approved") is True
            schema = entry.get("input_schema")
            assert isinstance(schema, dict), f"{tool_name} schema missing in {source}"
            assert schema.get("type") == "object"

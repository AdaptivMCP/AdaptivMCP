import main


def test_list_all_actions_includes_input_schema():
    result = main.list_all_actions(include_parameters=True)

    apply_tool = next(
        tool for tool in result["tools"] if tool["name"] == "update_files_and_open_pr"
    )

    assert apply_tool["input_schema"] is not None
    assert apply_tool["input_schema"].get("type") == "object"
    assert "properties" in apply_tool["input_schema"]

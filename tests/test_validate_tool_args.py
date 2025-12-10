import pytest

import main


@pytest.mark.asyncio
async def test_validate_tool_args_reports_missing_fields_and_enables_repair_flow():
    """Golden flow: invalid args for a known tool, then repaired using validate_tool_args.

    This mirrors the controller/assistant contract: assistants should
    (1) call the tool,
    (2) inspect the error,
    (3) read the schema via list_all_actions / controller metadata, then
    (4) call validate_tool_args to repair the payload before retrying.
    """

    # 1) Start with an incomplete payload (missing required 'head' field).
    invalid_args = {"full_name": "owner/repo", "base": "main"}

    validation = await main.validate_tool_args("compare_refs", invalid_args)

    assert validation["valid"] is False
    assert any("head" in error.get("message", "") for error in validation["errors"])

    # 2) Repair the payload using the error message / schema.
    repaired_args = {**invalid_args, "head": "feature"}

    repaired_validation = await main.validate_tool_args("compare_refs", repaired_args)

    assert repaired_validation["valid"] is True
    assert repaired_validation["errors"] == []


@pytest.mark.asyncio
async def test_validate_tool_args_passes_for_known_tool():
    result = await main.validate_tool_args(
        "compare_refs", {"full_name": "owner/repo", "base": "main", "head": "feature"}
    )

    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_validate_tool_args_unknown_tool_raises():
    with pytest.raises(ValueError):
        await main.validate_tool_args("missing_tool", {})


@pytest.mark.asyncio
async def test_validate_tool_args_batch_two_tools():
    args = {"full_name": "owner/repo", "base": "main", "head": "feature"}

    result = await main.validate_tool_args(
        tool_names=["compare_refs", "create_branch"],
        payload=args,
    )

    assert "results" in result
    assert isinstance(result["results"], list)
    assert len(result["results"]) == 2
    tools = {entry["tool"] for entry in result["results"]}
    assert {"compare_refs", "create_branch"} <= tools


@pytest.mark.asyncio
async def test_validate_tool_args_batch_too_many_tools_raises():
    tool_names = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10"]
    with pytest.raises(ValueError):
        await main.validate_tool_args(tool_names=tool_names, payload={})


@pytest.mark.asyncio
async def test_validate_tool_args_optional_null_fields_are_allowed():
    args = {
        "full_name": "owner/repo",
        "path": "file.txt",
        "patch": "",
        "message": None,
    }

    result = await main.validate_tool_args("apply_patch_and_commit", args)

    assert result["valid"] is True
    assert result["errors"] == []

    message_type = result["schema"]["properties"]["message"].get("type")
    types = message_type if isinstance(message_type, list) else [message_type]
    assert "null" in types

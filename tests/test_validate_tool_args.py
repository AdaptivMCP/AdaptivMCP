import pytest

import main


@pytest.mark.asyncio
async def test_validate_tool_args_reports_missing_fields_and_enables_repair_flow():
    """Golden flow: invalid args for a known tool, then repaired using validate_tool_args."""

    # Start with an incomplete payload (missing required 'full_name' field).
    invalid_args = {"branch": "main"}

    validation = await main.validate_tool_args("list_workflow_runs", invalid_args)

    assert validation["valid"] is False
    assert any("full_name" in error.get("message", "") for error in validation["errors"])

    # Repair the payload using the error message / schema.
    repaired_args = {**invalid_args, "full_name": "owner/repo"}

    repaired_validation = await main.validate_tool_args("list_workflow_runs", repaired_args)

    assert repaired_validation["valid"] is True
    assert repaired_validation["errors"] == []


@pytest.mark.asyncio
async def test_validate_tool_args_passes_for_known_tool():
    result = await main.validate_tool_args(
        "list_recent_failures", {"full_name": "owner/repo", "branch": "main", "limit": 3}
    )

    assert result["valid"] is True
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_validate_tool_args_unknown_tool_raises():
    with pytest.raises(ValueError):
        await main.validate_tool_args("missing_tool", {})


@pytest.mark.asyncio
async def test_validate_tool_args_batch_two_tools():
    payload = {"full_name": "owner/repo", "branch": "main", "limit": 3}

    result = await main.validate_tool_args(
        tool_names=["list_recent_failures", "list_workflow_runs"],
        payload=payload,
    )

    assert "results" in result
    assert isinstance(result["results"], list)
    assert len(result["results"]) == 2
    tools = {entry["tool"] for entry in result["results"]}
    assert {"list_recent_failures", "list_workflow_runs"} <= tools


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
        "updated_content": "hello\n",
        "message": None,
    }

    result = await main.validate_tool_args("apply_text_update_and_commit", args)

    assert result["valid"] is True
    assert result["errors"] == []

    message_type = result["schema"]["properties"]["message"].get("type")
    types = message_type if isinstance(message_type, list) else [message_type]
    assert "null" in types

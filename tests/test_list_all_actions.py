import pytest

import main


def test_list_all_actions_includes_input_schema():
    result = main.list_all_actions(include_parameters=True)

    apply_tool = next(
        tool for tool in result["tools"] if tool["name"] == "update_files_and_open_pr"
    )

    assert apply_tool["input_schema"] is not None
    assert apply_tool["input_schema"].get("type") == "object"
    assert "properties" in apply_tool["input_schema"]


def test_list_write_tools_includes_issue_helpers():
    tools = main.list_write_tools()["tools"]

    tool_names = {tool["name"] for tool in tools}

    assert {"create_issue", "update_issue", "comment_on_issue"} <= tool_names


def test_list_all_actions_compact_mode_truncates_descriptions():
    expanded = main.list_all_actions(include_parameters=False, compact=False)
    compact = main.list_all_actions(include_parameters=False, compact=True)

    expanded_tool = next(tool for tool in expanded["tools"] if tool["name"] == "run_command")
    compact_tool = next(tool for tool in compact["tools"] if tool["name"] == "run_command")

    assert compact["compact"] is True
    assert "tags" not in compact_tool
    assert len(compact_tool["description"]) < len(expanded_tool["description"])
    assert len(compact_tool["description"]) <= 200


@pytest.mark.asyncio
async def test_create_issue_builds_payload_and_calls_github_request(monkeypatch):
    calls = []

    async def fake_github_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, "kwargs": kwargs})
        # Echo a simple status so callers can assert on it.
        return {"status": "ok", "method": method, "path": path, **kwargs}

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    result = await main.create_issue(
        full_name="owner/repo",
        title="Test issue",
        body="Body text",
        labels=["bug", "high"],
        assignees=["alice"],
    )

    assert result["status"] == "ok"
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/repos/owner/repo/issues"
    assert call["kwargs"]["json_body"] == {
        "title": "Test issue",
        "body": "Body text",
        "labels": ["bug", "high"],
        "assignees": ["alice"],
    }


@pytest.mark.asyncio
async def test_create_issue_respects_write_gate(monkeypatch):
    async def fake_github_request(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("_github_request should not be called when writes are disabled")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", False)

    with pytest.raises(main.WriteNotAuthorizedError):
        await main.create_issue(full_name="owner/repo", title="Test issue")


@pytest.mark.asyncio
async def test_update_issue_minimal_payload(monkeypatch):
    calls = []

    async def fake_github_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, "kwargs": kwargs})
        return {"status": "ok"}

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    await main.update_issue(
        full_name="owner/repo",
        issue_number=42,
        title="New title",
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/repos/owner/repo/issues/42"
    assert call["kwargs"]["json_body"] == {"title": "New title"}


@pytest.mark.asyncio
async def test_update_issue_invalid_state_raises(monkeypatch):
    async def fake_github_request(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("_github_request should not be called for invalid state")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.update_issue(
            full_name="owner/repo",
            issue_number=1,
            state="invalid",
        )


@pytest.mark.asyncio
async def test_update_issue_requires_at_least_one_field(monkeypatch):
    async def fake_github_request(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("_github_request should not be called when no fields are provided")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.update_issue(full_name="owner/repo", issue_number=1)


@pytest.mark.asyncio
async def test_comment_on_issue_calls_expected_endpoint(monkeypatch):
    calls = []

    async def fake_github_request(method, path, **kwargs):
        calls.append({"method": method, "path": path, "kwargs": kwargs})
        return {"status": "ok"}

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    result = await main.comment_on_issue(
        full_name="owner/repo",
        issue_number=7,
        body="Hello from tests",
    )

    assert result["status"] == "ok"
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/repos/owner/repo/issues/7/comments"
    assert call["kwargs"]["json_body"] == {"body": "Hello from tests"}

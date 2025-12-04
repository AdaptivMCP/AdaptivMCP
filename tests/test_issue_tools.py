import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_create_issue_validates_full_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.create_issue(full_name="not-a-repo", title="Title")


@pytest.mark.asyncio
async def test_create_issue_sends_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    calls: dict[str, object] = {}

    async def fake_github_request(method: str, url: str, json_body=None, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["json_body"] = json_body
        return {"json": {"number": 123}}

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    result = await main.create_issue(
        full_name="owner/repo",
        title="Issue title",
        body="Body text",
        labels=["bug", "roadmap"],
        assignees=["user1"],
    )

    assert calls["method"] == "POST"
    assert calls["url"] == "/repos/owner/repo/issues"
    assert calls["json_body"] == {
        "title": "Issue title",
        "body": "Body text",
        "labels": ["bug", "roadmap"],
        "assignees": ["user1"],
    }
    assert "create issue in owner/repo" in calls["write_context"]
    assert result["json"]["number"] == 123


@pytest.mark.asyncio
async def test_update_issue_requires_at_least_one_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.update_issue(full_name="owner/repo", issue_number=1)


@pytest.mark.asyncio
async def test_update_issue_validates_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.update_issue(
            full_name="owner/repo", issue_number=1, state="invalid"
        )


@pytest.mark.asyncio
async def test_update_issue_sends_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    calls: dict[str, object] = {}

    async def fake_github_request(method: str, url: str, json_body=None, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["json_body"] = json_body
        return {"json": {"number": 1, "state": "closed"}}

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    result = await main.update_issue(
        full_name="owner/repo",
        issue_number=7,
        title="New title",
        body="Updated body",
        state="closed",
        labels=["bug"],
        assignees=["user1"],
    )

    assert calls["method"] == "PATCH"
    assert calls["url"] == "/repos/owner/repo/issues/7"
    assert calls["json_body"] == {
        "title": "New title",
        "body": "Updated body",
        "state": "closed",
        "labels": ["bug"],
        "assignees": ["user1"],
    }
    assert "update issue #7 in owner/repo" in calls["write_context"]
    assert result["json"]["state"] == "closed"


@pytest.mark.asyncio
async def test_comment_on_issue_validates_full_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.comment_on_issue("not-a-repo", issue_number=1, body="hi")


@pytest.mark.asyncio
async def test_comment_on_issue_sends_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    calls: dict[str, object] = {}

    async def fake_github_request(method: str, url: str, json_body=None, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["json_body"] = json_body
        return {"json": {"id": 999}}

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    result = await main.comment_on_issue(
        full_name="owner/repo", issue_number=42, body="Hello"
    )

    assert calls["method"] == "POST"
    assert calls["url"] == "/repos/owner/repo/issues/42/comments"
    assert calls["json_body"] == {"body": "Hello"}
    assert "comment on issue #42 in owner/repo" in calls["write_context"]
    assert result["json"]["id"] == 999


@pytest.mark.asyncio
async def test_issue_tools_propagate_github_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    async def fake_github_request(method: str, url: str, json_body=None, **kwargs):
        raise GitHubAPIError("GitHub API error 500 for /issues")

    monkeypatch.setattr(main, "_github_request", fake_github_request)

    with pytest.raises(GitHubAPIError):
        await main.create_issue(full_name="owner/repo", title="Title")

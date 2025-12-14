import pytest

import main


@pytest.mark.asyncio
async def test_create_pull_request_returns_structured_error(monkeypatch):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    def fake_effective_ref(full_name, ref):
        return ref

    def fake_ensure_write_allowed(context):
        return None

    async def fake_github_request(*args, **kwargs):
        raise main.GitHubAPIError("boom")

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main.server, "_ensure_write_allowed", fake_ensure_write_allowed)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    result = await main.create_pull_request(
        full_name="owner/repo", title="title", head="feature", base="main"
    )

    assert "error" in result
    assert result["error"]["context"] == "create_pull_request"
    assert "boom" in result["error"]["message"]
    # Path hint helps callers and logs identify the failing repo/head/base.
    assert result["error"]["path"] == "owner/repo feature->main"


@pytest.mark.asyncio
async def test_create_pull_request_uses_explicit_body(monkeypatch):
    """When a body is provided, it should be passed through unchanged."""

    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    def fake_effective_ref(full_name, ref):
        return ref

    def fake_ensure_write_allowed(context):
        return None

    captured_payload = {}

    async def fake_github_request(method, path, json_body=None, **kwargs):
        nonlocal captured_payload
        captured_payload = {
            "method": method,
            "path": path,
            "json_body": json_body,
        }
        return {"status_code": 201, "json": {"number": 1}}

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main.server, "_ensure_write_allowed", fake_ensure_write_allowed)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    body = "Explicit body from caller"

    result = await main.create_pull_request(
        full_name="owner/repo",
        title="My PR",
        head="feature-branch",
        base="main",
        body=body,
        draft=False,
    )

    assert result["status_code"] == 201
    assert captured_payload["json_body"]["body"] == body


@pytest.mark.asyncio
async def test_create_pull_request_generates_default_body_when_missing(monkeypatch):
    """When body is None, create_pull_request should generate a rich default body.

    This test focuses on ensuring that a non-empty body is sent when the
    caller omits one, without depending on the exact formatting of the template.
    """

    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    def fake_effective_ref(full_name, ref):
        return ref

    def fake_ensure_write_allowed(context):
        return None

    async def fake_compare_refs(full_name, base, head):  # type: ignore[override]
        return {
            "ahead_by": 2,
            "behind_by": 0,
            "total_commits": 2,
            "files": [
                {"filename": "main.py"},
                {"filename": "tests/test_create_pull_request.py"},
            ],
        }

    async def fake_list_workflow_runs(full_name, branch=None, per_page=3, page=1):  # type: ignore[override]
        return {
            "json": {
                "workflow_runs": [
                    {
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://example.com/workflow/1",
                    }
                ]
            }
        }

    captured_payload = {}

    async def fake_github_request(method, path, json_body=None, **kwargs):
        nonlocal captured_payload
        captured_payload = {
            "method": method,
            "path": path,
            "json_body": json_body,
        }
        return {"status_code": 201, "json": {"number": 1}}

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main.server, "_ensure_write_allowed", fake_ensure_write_allowed)
    monkeypatch.setattr(main, "compare_refs", fake_compare_refs)
    monkeypatch.setattr(main, "list_workflow_runs", fake_list_workflow_runs)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    result = await main.create_pull_request(
        full_name="owner/repo",
        title="My PR",
        head="feature-branch",
        base="main",
        body=None,
        draft=False,
    )

    assert result["status_code"] == 201
    body_text = captured_payload["json_body"].get("body")
    assert isinstance(body_text, str)
    assert "## Summary" in body_text
    assert "## Change summary" in body_text
    assert "## CI & quality" in body_text

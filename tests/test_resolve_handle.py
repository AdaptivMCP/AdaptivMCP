import pytest

import main


@pytest.mark.asyncio
async def test_resolve_handle_numeric_collects_issue_and_pr(monkeypatch):
    async def fake_fetch_issue(full_name: str, issue_number: int):
        return {
            "json": {
                "number": issue_number,
                "title": "Issue title",
                "state": "open",
                "html_url": "https://example.com/issue",
                "user": {"login": "octocat"},
                "labels": [{"name": "bug"}],
            }
        }

    async def fake_fetch_pr(full_name: str, pull_number: int):
        return {
            "json": {
                "number": pull_number,
                "title": "PR title",
                "state": "open",
                "draft": False,
                "merged": False,
                "html_url": "https://example.com/pr",
                "user": {"login": "octocat"},
                "head": {"ref": "feature/123"},
                "base": {"ref": "main"},
            }
        }

    monkeypatch.setattr(main, "fetch_issue", fake_fetch_issue)
    monkeypatch.setattr(main, "fetch_pr", fake_fetch_pr)

    result = await main.resolve_handle("owner/repo", handle="123")

    assert result["resolved_kinds"] == ["issue", "pull_request"]
    assert result["issue"]["title"] == "Issue title"
    assert result["pull_request"]["head_ref"] == "feature/123"


@pytest.mark.asyncio
async def test_resolve_handle_prefixed_pr(monkeypatch):
    async def fake_fetch_pr(full_name: str, pull_number: int):
        return {"json": {"number": pull_number, "title": "PR prefixed", "state": "open"}}

    monkeypatch.setattr(main, "fetch_pr", fake_fetch_pr)

    result = await main.resolve_handle("owner/repo", handle="pr:45")

    assert result["resolved_kinds"] == ["pull_request"]
    assert result["pull_request"]["number"] == 45
    assert result["issue"] is None


@pytest.mark.asyncio
async def test_resolve_handle_branch(monkeypatch):
    async def fake_get_branch_summary(full_name: str, branch: str, base: str = "main"):
        return {
            "branch": branch,
            "base": base,
            "compare": {"ahead_by": 1, "behind_by": 0, "status": "ahead", "total_commits": 1},
            "open_prs": [
                {
                    "number": 5,
                    "title": "Branch PR",
                    "state": "open",
                    "draft": False,
                    "html_url": "https://example.com/pr/5",
                    "head": {"ref": branch},
                    "base": {"ref": base},
                }
            ],
            "closed_prs": [],
            "latest_workflow_run": {"id": 10, "status": "queued", "head_branch": branch},
        }

    monkeypatch.setattr(main, "get_branch_summary", fake_get_branch_summary)

    result = await main.resolve_handle("owner/repo", handle="feature/foo")

    assert result["resolved_kinds"] == ["branch"]
    assert result["branch"]["compare"]["ahead_by"] == 1
    assert result["branch"]["open_prs"][0]["number"] == 5


@pytest.mark.asyncio
async def test_resolve_handle_invalid_returns_empty(monkeypatch):
    async def fake_get_branch_summary(full_name: str, branch: str, base: str = "main"):
        return {"compare_error": "Not Found"}

    monkeypatch.setattr(main, "get_branch_summary", fake_get_branch_summary)

    result = await main.resolve_handle("owner/repo", handle="???")

    assert result["resolved_kinds"] == []
    assert result["issue"] is None
    assert result["pull_request"] is None
    assert result["branch"] is None

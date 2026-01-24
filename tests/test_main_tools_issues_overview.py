from __future__ import annotations

from types import ModuleType

import pytest


@pytest.mark.asyncio
async def test_open_issue_context_matches_branches_and_prs(monkeypatch):
    """Exercise open_issue_context tokenization and PR matching logic."""

    from github_mcp.main_tools import issues

    class DummyMain(ModuleType):
        pass

    m = DummyMain("main")

    async def fetch_issue(full_name: str, issue_number: int):
        assert full_name == "o/r"
        assert issue_number == 123
        return {
            "json": {
                "number": 123,
                "title": "Example",
                "body": "Issue body",
            }
        }

    async def list_branches(full_name: str, per_page: int = 30, page: int = 1):
        assert full_name == "o/r"
        assert per_page == 100
        return {
            "json": [
                {"name": "feature/123-fix"},
                {"name": "chore/no-issue"},
                {"name": "bugfix_999_other"},
            ]
        }

    async def list_pull_requests(
        full_name: str, state: str = "open", per_page: int = 30, page: int = 1
    ):
        assert full_name == "o/r"
        assert state == "all"
        return {
            "json": [
                {
                    "number": 10,
                    "title": "Fixes 123 - update docs",
                    "body": "Body text",
                    "state": "open",
                    "draft": False,
                    "html_url": "https://example.invalid/pr/10",
                    "head": {"ref": "feature/123-fix"},
                    "base": {"ref": "main"},
                },
                {
                    "number": 11,
                    "title": "Unrelated",
                    "body": "No mention",
                    "state": "closed",
                    "draft": False,
                    "html_url": "https://example.invalid/pr/11",
                    "head": {"ref": "chore/no-issue"},
                    "base": {"ref": "main"},
                },
            ]
        }

    m.fetch_issue = fetch_issue  # type: ignore[attr-defined]
    m.list_branches = list_branches  # type: ignore[attr-defined]
    m.list_pull_requests = list_pull_requests  # type: ignore[attr-defined]

    monkeypatch.setattr(issues, "_main", lambda: m)

    ctx = await issues.open_issue_context("o/r", 123)
    assert isinstance(ctx, dict)
    assert ctx.get("issue", {}).get("number") == 123
    assert ctx.get("candidate_branches") == ["feature/123-fix"]

    open_prs = ctx.get("open_prs")
    assert isinstance(open_prs, list) and len(open_prs) == 1
    assert open_prs[0]["number"] == 10
    assert open_prs[0]["head"]["ref"] == "feature/123-fix"


@pytest.mark.asyncio
async def test_get_issue_overview_normalizes_fields_and_extracts_checklists(
    monkeypatch,
):
    """Cover get_issue_overview normalization and checklist extraction."""

    from github_mcp.main_tools import issues

    class DummyMain(ModuleType):
        pass

    m = DummyMain("main")

    async def open_issue_context(full_name: str, issue_number: int):
        assert full_name == "o/r"
        assert issue_number == 5
        return {
            "issue": {
                "number": 5,
                "title": "Checklist test",
                "state": "open",
                "html_url": "https://example.invalid/issues/5",
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": "2020-01-02T00:00:00Z",
                "closed_at": None,
                "user": {
                    "login": "alice",
                    "html_url": "https://example.invalid/u/alice",
                },
                "assignees": [
                    {"login": "bob", "html_url": "https://example.invalid/u/bob"}
                ],
                "labels": [{"name": "bug", "color": "ff0000"}, "help wanted"],
                "body": "- [ ] first\n- [x] second\n",
            },
            "candidate_branches": ["feature/5-fix"],
            "open_prs": [{"number": 99, "title": "Fix 5", "state": "open"}],
            "closed_prs": [],
            "comments": [
                {"body": "- [ ] from comment"},
                {"body": "not a checklist"},
            ],
        }

    m.open_issue_context = open_issue_context  # type: ignore[attr-defined]
    monkeypatch.setattr(issues, "_main", lambda: m)

    overview = await issues.get_issue_overview("o/r", 5)
    assert isinstance(overview, dict)

    issue = overview.get("issue")
    assert isinstance(issue, dict)
    assert issue.get("number") == 5
    assert issue.get("user") == {
        "login": "alice",
        "html_url": "https://example.invalid/u/alice",
    }

    labels = issue.get("labels")
    assert isinstance(labels, list)
    assert {
        label.get("name") for label in labels if isinstance(label, dict)
    }.issuperset({"bug", "help wanted"})

    checklist = overview.get("checklist_items")
    assert isinstance(checklist, list)
    texts = [c.get("text") for c in checklist if isinstance(c, dict)]
    assert "first" in texts
    assert "second" in texts
    assert "from comment" in texts

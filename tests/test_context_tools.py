import pytest

import main


@pytest.mark.asyncio
async def test_get_branch_summary_collects_data(monkeypatch):
    async def fake_compare(full_name: str, base: str, head: str):
        return {"ahead_by": 2, "behind_by": 1, "base": base, "head": head}

    async def fake_list_prs(full_name: str, state: str = "open", head=None, base=None, per_page: int = 30, page: int = 1):
        return {
            "json": [
                {
                    "number": 123,
                    "state": state,
                    "head": {"ref": head},
                    "base": {"ref": base},
                }
            ]
        }

    async def fake_list_runs(full_name: str, branch=None, status=None, event=None, per_page: int = 30, page: int = 1):
        return {"json": {"workflow_runs": [{"id": 99, "head_branch": branch}]}}

    monkeypatch.setattr(main, "compare_refs", fake_compare)
    monkeypatch.setattr(main, "list_pull_requests", fake_list_prs)
    monkeypatch.setattr(main, "list_workflow_runs", fake_list_runs)

    result = await main.get_branch_summary("owner/repo", branch="feature", base="main")

    assert result["branch"] == "feature"
    assert result["compare"]["ahead_by"] == 2
    assert result["open_prs"][0]["number"] == 123
    assert result["latest_workflow_run"]["id"] == 99


@pytest.mark.asyncio
async def test_open_issue_context_collects_branches_and_prs(monkeypatch):
    async def fake_fetch_issue(full_name: str, issue_number: int):
        return {"json": {"number": issue_number, "title": "Issue"}}

    async def fake_list_branches(full_name: str, per_page: int = 100, page: int = 1):
        return {"json": [{"name": "feature/issue-5"}, {"name": "main"}]}

    async def fake_list_prs(full_name: str, state: str = "open", head=None, base=None, per_page: int = 30, page: int = 1):
        return {
            "json": [
                {
                    "number": 10,
                    "state": "open",
                    "title": "Fix issue 5",
                    "head": {"ref": "feature/issue-5"},
                    "body": "Resolves #5",
                }
            ]
        }

    monkeypatch.setattr(main, "fetch_issue", fake_fetch_issue)
    monkeypatch.setattr(main, "list_branches", fake_list_branches)
    monkeypatch.setattr(main, "list_pull_requests", fake_list_prs)

    result = await main.open_issue_context("owner/repo", issue_number=5)

    assert result["issue"]["number"] == 5
    assert "feature/issue-5" in result["candidate_branches"]
    assert result["open_prs"][0]["number"] == 10

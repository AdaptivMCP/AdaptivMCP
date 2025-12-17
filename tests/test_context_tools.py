import pytest

import main


@pytest.mark.asyncio
async def test_open_issue_context_collects_branches_and_prs(monkeypatch):
    async def fake_fetch_issue(full_name: str, issue_number: int):
        return {"json": {"number": issue_number, "title": "Issue"}}

    async def fake_list_branches(full_name: str, per_page: int = 100, page: int = 1):
        return {"json": [{"name": "feature/issue-5"}, {"name": "main"}]}

    async def fake_list_prs(
        full_name: str, state: str = "open", head=None, base=None, per_page: int = 30, page: int = 1
    ):
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


@pytest.mark.asyncio
async def test_get_issue_overview_normalizes_issue_and_checklists(monkeypatch):
    async def fake_open_issue_context(full_name: str, issue_number: int):
        return {
            "issue": {
                "number": issue_number,
                "title": "Issue",
                "state": "open",
                "html_url": "https://example.test/issue/5",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00Z",
                "closed_at": None,
                "user": {"login": "author", "html_url": "https://example.test/author"},
                "assignees": [
                    {"login": "assignee1", "html_url": "https://example.test/assignee1"},
                    {"login": "assignee2"},
                ],
                "labels": [
                    {"name": "bug", "color": "ff0000"},
                    "help wanted",
                ],
                "body": "- [ ] top level task\nSome text\n- [x] done task",
            },
            "comments": [
                {"body": "- [ ] follow-up task in comment"},
                {"body": "not a checklist line"},
            ],
            "candidate_branches": ["feature/issue-5"],
            "open_prs": [{"number": 10}],
            "closed_prs": [{"number": 11}],
        }

    monkeypatch.setattr(main, "open_issue_context", fake_open_issue_context)

    result = await main.get_issue_overview("owner/repo", issue_number=5)

    assert result["issue"]["number"] == 5
    assert result["issue"]["title"] == "Issue"
    assert result["issue"]["user"] == {"login": "author", "html_url": "https://example.test/author"}
    # labels normalized to dicts
    assert {"name": "bug", "color": "ff0000"} in result["issue"]["labels"]
    assert {"name": "help wanted"} in result["issue"]["labels"]
    # checklist items from body and comments
    texts = {item["text"]: item["source"] for item in result["checklist_items"]}
    assert "top level task" in texts
    assert texts["top level task"] == "issue_body"
    assert "done task" in texts
    assert "follow-up task in comment" in texts
    assert texts["follow-up task in comment"] == "comment"
    # branches and PRs forwarded
    assert result["candidate_branches"] == ["feature/issue-5"]
    assert result["open_prs"][0]["number"] == 10
    assert result["closed_prs"][0]["number"] == 11


@pytest.mark.asyncio
async def test_get_pr_overview_collects_pr_files_and_ci(monkeypatch):
    async def fake_fetch_pr(full_name: str, pull_number: int):
        return {
            "json": {
                "number": pull_number,
                "title": "Add feature",
                "state": "open",
                "draft": False,
                "merged": False,
                "html_url": "https://example.test/pr/123",
                "user": {"login": "author", "html_url": "https://example.test/author"},
                "head": {"ref": "feature/branch", "sha": "abc123"},
                "base": {"ref": "main"},
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00Z",
                "closed_at": None,
                "merged_at": None,
            }
        }

    async def fake_list_pr_changed_filenames(
        full_name: str, pull_number: int, per_page: int = 100, page: int = 1
    ):
        return {
            "json": [
                {
                    "filename": "main.py",
                    "status": "modified",
                    "additions": 10,
                    "deletions": 2,
                    "changes": 12,
                }
            ]
        }

    async def fake_get_commit_combined_status(full_name: str, ref: str):
        return {"json": {"state": "success", "total_count": 1}}

    async def fake_list_workflow_runs(
        full_name: str,
        branch=None,
        status=None,
        event=None,
        per_page: int = 30,
        page: int = 1,
    ):
        return {
            "json": {
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": branch,
                        "head_sha": "abc123",
                        "html_url": "https://example.test/runs/1",
                        "created_at": "2025-01-02T00:00:00Z",
                        "updated_at": "2025-01-02T00:05:00Z",
                    }
                ]
            }
        }

    import main

    monkeypatch.setattr(main, "fetch_pr", fake_fetch_pr)
    monkeypatch.setattr(main, "list_pr_changed_filenames", fake_list_pr_changed_filenames)
    monkeypatch.setattr(main, "get_commit_combined_status", fake_get_commit_combined_status)
    monkeypatch.setattr(main, "list_workflow_runs", fake_list_workflow_runs)

    result = await main.get_pr_overview("owner/repo", pull_number=123)

    assert result["repository"] == "owner/repo"
    assert result["pull_number"] == 123
    assert result["pr"]["number"] == 123
    assert result["pr"]["title"] == "Add feature"
    assert result["pr"]["user"] == {"login": "author", "html_url": "https://example.test/author"}
    assert result["files"][0]["filename"] == "main.py"
    assert result["status_checks"]["state"] == "success"
    assert result["workflow_runs"][0]["id"] == 1


@pytest.mark.asyncio
async def test_recent_prs_for_branch_groups_open_and_closed(monkeypatch):
    calls = []

    async def fake_list_prs(
        full_name: str,
        state: str = "open",
        head=None,
        base=None,
        per_page: int = 30,
        page: int = 1,
    ):
        calls.append(
            {
                "full_name": full_name,
                "state": state,
                "head": head,
                "per_page": per_page,
                "page": page,
            }
        )
        if state == "open":
            return {
                "json": [
                    {
                        "number": 1,
                        "title": "Open PR",
                        "state": "open",
                        "html_url": "https://example.test/pr/1",
                        "user": {"login": "author", "html_url": "https://example.test/author"},
                        "head": {"ref": "feature/branch", "sha": "open-sha"},
                        "base": {"ref": "main"},
                    }
                ]
            }
        else:
            return {
                "json": [
                    {
                        "number": 2,
                        "title": "Closed PR",
                        "state": "closed",
                        "html_url": "https://example.test/pr/2",
                        "user": {"login": "author", "html_url": "https://example.test/author"},
                        "head": {"ref": "feature/branch", "sha": "closed-sha"},
                        "base": {"ref": "main"},
                    }
                ]
            }

    monkeypatch.setattr(main, "list_pull_requests", fake_list_prs)

    result = await main.recent_prs_for_branch(
        "owner/repo",
        branch="feature/branch",
        include_closed=True,
    )

    assert result["full_name"] == "owner/repo"
    assert result["branch"] == "feature/branch"
    assert result["open"][0]["number"] == 1
    assert result["closed"][0]["number"] == 2


@pytest.mark.asyncio
async def test_get_workflow_run_overview_includes_failed_and_longest_jobs(monkeypatch):
    async def fake_get_workflow_run(full_name: str, run_id: int):
        return {
            "json": {
                "id": run_id,
                "name": "CI",
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "feature/test",
                "head_sha": "abc123",
                "run_attempt": 1,
                "created_at": "2025-01-02T00:00:00Z",
                "updated_at": "2025-01-02T00:10:00Z",
                "html_url": "https://example.test/runs/1",
            }
        }

    async def fake_list_workflow_run_jobs(
        full_name: str, run_id: int, per_page: int = 30, page: int = 1
    ):
        return {
            "json": {
                "jobs": [
                    {
                        "id": 10,
                        "name": "tests",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": "2025-01-02T00:00:00Z",
                        "completed_at": "2025-01-02T00:03:00Z",
                        "html_url": "https://example.test/job/10",
                    },
                    {
                        "id": 20,
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "failure",
                        "started_at": "2025-01-02T00:03:00Z",
                        "completed_at": "2025-01-02T00:09:00Z",
                        "html_url": "https://example.test/job/20",
                    },
                ]
            }
        }

    monkeypatch.setattr(main, "get_workflow_run", fake_get_workflow_run)
    monkeypatch.setattr(main, "list_workflow_run_jobs", fake_list_workflow_run_jobs)

    result = await main.get_workflow_run_overview("owner/repo", run_id=1)

    assert result["full_name"] == "owner/repo"
    assert result["run"]["id"] == 1
    assert result["run"]["conclusion"] == "failure"

    jobs = result["jobs"]
    assert len(jobs) == 2
    assert all("duration_seconds" in job for job in jobs)
    assert jobs[0]["duration_seconds"] is not None

    failed_ids = [job["id"] for job in result["failed_jobs"]]
    assert failed_ids == [20]

    longest_ids = [job["id"] for job in result["longest_jobs"]]
    assert longest_ids[0] == 20
    assert set(longest_ids) >= {10, 20}


@pytest.mark.asyncio
async def test_get_workflow_run_overview_handles_missing_timestamps(monkeypatch):
    async def fake_get_workflow_run(full_name: str, run_id: int):
        return {"json": {"id": run_id}}

    async def fake_list_workflow_run_jobs(
        full_name: str, run_id: int, per_page: int = 30, page: int = 1
    ):
        return {
            "json": {
                "jobs": [
                    {
                        "id": 30,
                        "name": "no-timestamps",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": None,
                        "completed_at": None,
                        "html_url": "https://example.test/job/30",
                    }
                ]
            }
        }

    monkeypatch.setattr(main, "get_workflow_run", fake_get_workflow_run)
    monkeypatch.setattr(main, "list_workflow_run_jobs", fake_list_workflow_run_jobs)

    result = await main.get_workflow_run_overview("owner/repo", run_id=2)

    assert result["run"]["id"] == 2
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["duration_seconds"] is None
    assert result["failed_jobs"] == []
    assert result["longest_jobs"] == []

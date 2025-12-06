import pytest

import main


@pytest.mark.asyncio
async def test_list_recent_failures_filters_conclusions(monkeypatch):
    async def fake_list_workflow_runs(full_name, branch=None, status=None, event=None, per_page=30, page=1):
        return {
            "json": {
                "workflow_runs": [
                    {"id": 1, "conclusion": "success", "status": "completed"},
                    {"id": 2, "conclusion": "failure", "status": "completed"},
                    {"id": 3, "conclusion": "cancelled", "status": "completed"},
                    {"id": 4, "conclusion": "neutral", "status": "completed"},
                    {"id": 5, "conclusion": "timed_out", "status": "completed"},
                ]
            }
        }

    monkeypatch.setattr(main, "list_workflow_runs", fake_list_workflow_runs)

    result = await main.list_recent_failures("owner/repo", branch="main", limit=10)
    ids = [run["id"] for run in result["runs"]]
    assert ids == [2, 3, 5]
    assert result["full_name"] == "owner/repo"
    assert result["branch"] == "main"


@pytest.mark.asyncio
async def test_list_recent_failures_enforces_limit(monkeypatch):
    async def fake_list_workflow_runs(full_name, branch=None, status=None, event=None, per_page=30, page=1):
        runs = []
        for i in range(1, 6):
            runs.append({"id": i, "conclusion": "failure", "status": "completed"})
        return {"json": {"workflow_runs": runs}}

    monkeypatch.setattr(main, "list_workflow_runs", fake_list_workflow_runs)

    result = await main.list_recent_failures("owner/repo", branch="main", limit=2)
    assert len(result["runs"]) == 2
    assert [run["id"] for run in result["runs"]] == [1, 2]


@pytest.mark.asyncio
async def test_list_recent_failures_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        await main.list_recent_failures("owner/repo", limit=0)
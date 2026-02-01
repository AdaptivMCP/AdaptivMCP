from __future__ import annotations

from types import ModuleType

import pytest


class _AsyncNullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Resp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, *, get_map: dict[str, _Resp], post_map: dict[str, _Resp]):
        self.get_map = get_map
        self.post_map = post_map
        self.calls: list[tuple[str, str, object | None]] = []

    async def get(self, path: str):
        self.calls.append(("GET", path, None))
        return self.get_map.get(path, _Resp(500, text="missing stub"))

    async def post(self, path: str, json=None):
        self.calls.append(("POST", path, json))
        return self.post_map.get(path, _Resp(500, text="missing stub"))


class _GitHubAPIError(RuntimeError):
    pass


def _mk_main(*, client: _DummyClient):
    m = ModuleType("main")
    m._effective_ref_for_repo = lambda _full, ref: ref
    m._github_client_instance = lambda: client
    m._get_concurrency_semaphore = lambda: _AsyncNullCtx()
    m.GitHubAPIError = _GitHubAPIError

    async def _list_pull_requests(
        full_name: str, *, state: str, head: str | None, base: str
    ):
        return {
            "status_code": 200,
            "json": [
                {
                    "id": 1,
                    "state": state,
                    "head": head,
                    "base": base,
                    "repo": full_name,
                }
            ],
        }

    async def _list_workflow_runs(full_name: str, *, branch: str, per_page: int = 1):
        return {
            "status_code": 200,
            "json": {
                "workflow_runs": [{"id": 99, "branch": branch, "repo": full_name}]
            },
        }

    m.list_pull_requests = _list_pull_requests
    m.list_workflow_runs = _list_workflow_runs
    return m


@pytest.mark.asyncio
async def test_create_branch_raises_when_base_ref_missing_and_from_ref_not_sha(
    monkeypatch,
):
    from github_mcp.main_tools import branches

    client = _DummyClient(
        get_map={
            "/repos/o/r/git/ref/heads/not-there": _Resp(404, payload={}),
            "/repos/o/r/git/ref/tags/not-there": _Resp(404, payload={}),
        },
        post_map={},
    )

    dummy_main = _mk_main(client=client)
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    with pytest.raises(_GitHubAPIError):
        await branches.create_branch("o/r", "feature", from_ref="not-there")


@pytest.mark.asyncio
async def test_create_branch_accepts_sha_when_base_ref_missing(monkeypatch):
    from github_mcp.main_tools import branches

    sha = "a" * 40
    client = _DummyClient(
        get_map={
            f"/repos/o/r/git/ref/heads/{sha}": _Resp(404, payload={}),
            f"/repos/o/r/git/ref/tags/{sha}": _Resp(404, payload={}),
        },
        post_map={
            "/repos/o/r/git/refs": _Resp(201, payload={"ref": "refs/heads/feature"}),
        },
    )

    dummy_main = _mk_main(client=client)
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    out = await branches.create_branch("o/r", "feature", from_ref=sha)
    assert out["status_code"] == 201

    # Verify we posted the sha in the create body
    posts = [c for c in client.calls if c[0] == "POST"]
    assert posts
    method, path, body = posts[-1]
    assert path == "/repos/o/r/git/refs"
    assert isinstance(body, dict)
    assert body["sha"] == sha


@pytest.mark.asyncio
async def test_ensure_branch_strips_and_rejects_blank(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(get_map={}, post_map={})
    dummy_main = _mk_main(client=client)
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    with pytest.raises(ValueError):
        await branches.ensure_branch("o/r", "   ")


@pytest.mark.asyncio
async def test_get_branch_summary_includes_prs_and_latest_workflow(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(get_map={}, post_map={})
    dummy_main = _mk_main(client=client)
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    summary = await branches.get_branch_summary("o/r", branch="feature", base="main")

    assert summary["branch"] == "feature"
    assert summary["base"] == "main"

    # PRs should be passed through
    assert summary["open_prs"] and summary["open_prs"][0]["state"] == "open"
    assert summary["closed_prs"] and summary["closed_prs"][0]["state"] == "closed"

    # Workflow run should be extracted
    assert summary["latest_workflow_run"] == {
        "id": 99,
        "branch": "feature",
        "repo": "o/r",
    }
    assert summary["workflow_error"] is None


@pytest.mark.asyncio
async def test_get_latest_branch_status_uses_normalizer_when_present(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(get_map={}, post_map={})
    dummy_main = _mk_main(client=client)

    def _normalize_branch_summary(summary: dict):
        return {"normalized": True, "summary": summary}

    dummy_main._normalize_branch_summary = _normalize_branch_summary
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    out = await branches.get_latest_branch_status("o/r", branch="feature", base="main")
    assert out["normalized"] is True
    assert out["summary"]["branch"] == "feature"


@pytest.mark.asyncio
async def test_get_branch_summary_sets_workflow_error_on_exception(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(get_map={}, post_map={})
    dummy_main = _mk_main(client=client)

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    dummy_main.list_workflow_runs = _boom
    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    summary = await branches.get_branch_summary("o/r", branch="feature", base="main")
    assert summary["latest_workflow_run"] is None
    assert summary["workflow_error"]

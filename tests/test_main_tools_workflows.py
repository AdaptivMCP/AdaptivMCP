from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeResp:
    status_code: int = 200
    text: str = ""
    headers: dict[str, str] | None = None
    content: bytes = b""
    json_data: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        return self.json_data or {}


class FakeClient:
    def __init__(self):
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.send_calls: list[tuple[Any, bool]] = []
        self._get_queue: list[FakeResp] = []
        self._post_queue: list[FakeResp] = []
        self._send_queue: list[FakeResp] = []

    def queue_get(self, *resps: FakeResp) -> None:
        self._get_queue.extend(resps)

    def queue_post(self, *resps: FakeResp) -> None:
        self._post_queue.extend(resps)

    def queue_send(self, *resps: FakeResp) -> None:
        self._send_queue.extend(resps)

    def build_request(
        self, method: str, path: str, headers: dict[str, str] | None = None
    ):
        # Just return a small, inspectable payload.
        return {"method": method, "path": path, "headers": headers or {}}

    async def send(self, request: Any, follow_redirects: bool = False) -> FakeResp:
        self.send_calls.append((request, follow_redirects))
        if self._send_queue:
            return self._send_queue.pop(0)
        return FakeResp(status_code=500, text="no queued response")

    async def get(self, path: str) -> FakeResp:
        self.get_calls.append(path)
        if self._get_queue:
            return self._get_queue.pop(0)
        return FakeResp(status_code=500, text="no queued response")

    async def post(self, path: str, json: dict[str, Any] | None = None) -> FakeResp:
        self.post_calls.append((path, json))
        if self._post_queue:
            return self._post_queue.pop(0)
        return FakeResp(status_code=500, text="no queued response")


class FakeLoop:
    def __init__(self, start: float = 0.0):
        self.now = float(start)

    def time(self) -> float:
        return float(self.now)


def _install_fake_loop(monkeypatch, *, module, loop: FakeLoop):
    """Patch module.asyncio.get_running_loop + module.asyncio.sleep to be deterministic."""

    monkeypatch.setattr(module.asyncio, "get_running_loop", lambda: loop)

    async def _fake_sleep(seconds: float):
        # Advance wall clock deterministically.
        loop.now += float(seconds)

    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep)


class FakeMain:
    def __init__(self):
        self._github_request_calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self._list_runs_calls: list[dict[str, Any]] = []
        self._list_jobs_calls: list[dict[str, Any]] = []
        self._get_run_calls: list[tuple[str, int]] = []

        self.client = FakeClient()
        self._list_runs_queue: list[dict[str, Any]] = []
        self._list_jobs_queue: list[dict[str, Any]] = []
        self._get_run_queue: list[dict[str, Any]] = []

    @contextlib.asynccontextmanager
    async def _get_concurrency_semaphore(self):
        yield

    def _github_client_instance(self):
        return self.client

    async def _github_request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ):
        self._github_request_calls.append((method, path, params))
        return {"method": method, "path": path, "params": params or {}, "json": {}}

    def queue_list_workflow_runs(self, *responses: dict[str, Any]) -> None:
        self._list_runs_queue.extend(responses)

    async def list_workflow_runs(self, **kwargs):
        self._list_runs_calls.append(kwargs)
        if self._list_runs_queue:
            return self._list_runs_queue.pop(0)
        return {"json": {"workflow_runs": []}}

    def queue_list_workflow_run_jobs(self, *responses: dict[str, Any]) -> None:
        self._list_jobs_queue.extend(responses)

    async def list_workflow_run_jobs(
        self, full_name: str, run_id: int, per_page: int = 30, page: int = 1
    ):
        self._list_jobs_calls.append(
            {
                "full_name": full_name,
                "run_id": run_id,
                "per_page": per_page,
                "page": page,
            }
        )
        if self._list_jobs_queue:
            return self._list_jobs_queue.pop(0)
        return {"json": {"jobs": []}}

    def queue_get_workflow_run(self, *responses: dict[str, Any]) -> None:
        self._get_run_queue.extend(responses)

    async def get_workflow_run(self, full_name: str, run_id: int):
        self._get_run_calls.append((full_name, run_id))
        if self._get_run_queue:
            return self._get_run_queue.pop(0)
        return {"json": {"id": run_id}}


@pytest.mark.asyncio
async def test_list_workflow_runs_builds_params_and_validates(monkeypatch):
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    out = await workflows.list_workflow_runs(
        "o/r",
        branch="main",
        status="completed",
        event="push",
        per_page=5,
        page=2,
    )

    assert out["path"].endswith("/repos/o/r/actions/runs")
    assert fake._github_request_calls == [
        (
            "GET",
            "/repos/o/r/actions/runs",
            {
                "per_page": 5,
                "page": 2,
                "branch": "main",
                "status": "completed",
                "event": "push",
            },
        )
    ]

    with pytest.raises(ValueError):
        await workflows.list_workflow_runs("not-a-repo")
    with pytest.raises(ValueError):
        await workflows.list_workflow_runs("o/r", per_page=0)
    with pytest.raises(ValueError):
        await workflows.list_workflow_runs("o/r", page=0)


@pytest.mark.asyncio
async def test_list_recent_failures_filters_and_limits(monkeypatch):
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    fake.queue_list_workflow_runs(
        {
            "json": {
                "workflow_runs": [
                    {
                        "id": 1,
                        "status": "completed",
                        "conclusion": "success",
                        "name": "ok",
                    },
                    {
                        "id": 2,
                        "status": "completed",
                        "conclusion": "failure",
                        "name": "bad",
                    },
                    {
                        "id": 3,
                        "status": "completed",
                        "conclusion": "neutral",
                        "name": "neutral",
                    },
                    {
                        "id": 4,
                        "status": "in_progress",
                        "conclusion": None,
                        "name": "running",
                    },
                    {
                        "id": 5,
                        "status": "completed",
                        "conclusion": "cancelled",
                        "name": "cancel",
                    },
                    # Included via the second condition (completed + non-success-ish conclusion).
                    {
                        "id": 6,
                        "status": "completed",
                        "conclusion": "stale",
                        "name": "weird",
                    },
                ]
            }
        }
    )

    out = await workflows.list_recent_failures("o/r", branch="main", limit=2)

    assert out["limit"] == 2
    assert [r["id"] for r in out["runs"]] == [2, 5]

    # limit=2 => per_page is clamped to at least 10.
    assert fake._list_runs_calls == [
        {"full_name": "o/r", "branch": "main", "per_page": 10, "page": 1}
    ]

    with pytest.raises(ValueError):
        await workflows.list_recent_failures("o/r", limit=0)


@pytest.mark.asyncio
async def test_get_workflow_run_overview_paginates_and_summarizes(monkeypatch):
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    fake.queue_get_workflow_run(
        {
            "json": {
                "id": 99,
                "name": "CI",
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "main",
                "head_sha": "abc",
                "run_attempt": 1,
                "created_at": "2099-01-01T00:00:00Z",
                "updated_at": "2099-01-01T00:01:00Z",
                "html_url": "https://example/run/99",
            }
        }
    )

    # First page returns jobs; second page repeats IDs to trigger duplicate-page guard.
    fake.queue_list_workflow_run_jobs(
        {
            "json": {
                "jobs": [
                    {
                        "id": 1,
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "failure",
                        "started_at": "2099-01-01T00:00:00Z",
                        "completed_at": "2099-01-01T00:00:10Z",
                        "html_url": "https://example/job/1",
                    },
                    {
                        "id": 2,
                        "name": "tests",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": "2099-01-01T00:00:00Z",
                        "completed_at": "2099-01-01T00:01:40Z",
                        "html_url": "https://example/job/2",
                    },
                ]
            }
        },
        {
            "json": {
                "jobs": [
                    {"id": 1, "name": "lint"},
                    {"id": 2, "name": "tests"},
                ]
            }
        },
    )

    out = await workflows.get_workflow_run_overview("o/r", run_id=99, max_jobs=500)

    assert out["run"]["id"] == 99
    assert len(out["jobs"]) == 2
    assert [j["id"] for j in out["failed_jobs"]] == [1]

    # Longest job should be job 2 (~100s).
    assert out["longest_jobs"][0]["id"] == 2
    assert int(out["longest_jobs"][0]["duration_seconds"] or 0) == 100

    log = "\n".join(out["controller_log"])
    assert "Workflow run overview" in log
    assert "Longest jobs by duration" in log
    assert "tests: 100s" in log

    with pytest.raises(ValueError):
        await workflows.get_workflow_run_overview("o/r", run_id=1, max_jobs=0)


@pytest.mark.asyncio
async def test_get_job_logs_handles_zip_and_errors(monkeypatch):
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    # Zip response uses decode hook.
    def _decode(payload: bytes) -> str:
        assert payload == b"zipbytes"
        return "decoded logs"

    fake._decode_zipped_job_logs = _decode  # type: ignore[attr-defined]
    fake.client.queue_send(
        FakeResp(
            status_code=200,
            headers={"Content-Type": "application/zip"},
            content=b"zipbytes",
            text="fallback",
        )
    )

    out_zip = await workflows.get_job_logs("o/r", job_id=123)
    assert out_zip["content_type"].startswith("application/zip")
    assert out_zip["logs"] == "decoded logs"

    # Non-zip uses resp.text.
    fake.client.queue_send(
        FakeResp(
            status_code=200,
            headers={"Content-Type": "text/plain"},
            text="plain logs",
        )
    )
    out_plain = await workflows.get_job_logs("o/r", job_id=456)
    assert out_plain["logs"] == "plain logs"

    # Error status raises.
    fake.client.queue_send(
        FakeResp(status_code=404, headers={"Content-Type": "text/plain"}, text="nope")
    )
    with pytest.raises(GitHubAPIError):
        await workflows.get_job_logs("o/r", job_id=999)


@pytest.mark.asyncio
async def test_wait_for_workflow_run_completes_and_times_out(monkeypatch):
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    loop = FakeLoop(start=0)
    _install_fake_loop(monkeypatch, module=workflows, loop=loop)

    # First: completes after one poll.
    fake.client.queue_get(
        FakeResp(status_code=200, json_data={"status": "queued", "conclusion": None}),
        FakeResp(
            status_code=200, json_data={"status": "completed", "conclusion": "success"}
        ),
    )

    out_done = await workflows.wait_for_workflow_run(
        "o/r", run_id=1, timeout_seconds=10, poll_interval_seconds=1
    )
    assert out_done["status"] == "completed"
    assert out_done["conclusion"] == "success"

    # Second: times out (uses > end_time comparison).
    fake.client.queue_get(
        FakeResp(
            status_code=200, json_data={"status": "in_progress", "conclusion": None}
        ),
        FakeResp(
            status_code=200, json_data={"status": "in_progress", "conclusion": None}
        ),
        FakeResp(
            status_code=200, json_data={"status": "in_progress", "conclusion": None}
        ),
    )

    loop.now = 0
    out_timeout = await workflows.wait_for_workflow_run(
        "o/r", run_id=2, timeout_seconds=1, poll_interval_seconds=1
    )
    assert out_timeout.get("timeout") is True
    assert out_timeout["status"] == "in_progress"


@pytest.mark.asyncio
async def test_trigger_workflow_dispatch_success_and_failure(monkeypatch):
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    fake.client.queue_post(FakeResp(status_code=204, text=""))

    out = await workflows.trigger_workflow_dispatch(
        "o/r", workflow="ci.yml", ref="main", inputs={"b": 2, "a": 1}
    )

    assert out["status_code"] == 204
    assert fake.client.post_calls == [
        (
            "/repos/o/r/actions/workflows/ci.yml/dispatches",
            {"ref": "main", "inputs": {"b": 2, "a": 1}},
        )
    ]
    log = "\n".join(out["controller_log"])
    assert "Inputs keys" in log
    assert "['a', 'b']" in log

    fake.client.queue_post(FakeResp(status_code=400, text="bad"))
    with pytest.raises(GitHubAPIError):
        await workflows.trigger_workflow_dispatch("o/r", workflow="ci.yml", ref="main")


@pytest.mark.asyncio
async def test_trigger_and_wait_for_workflow_picks_most_recent(monkeypatch):
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    loop = FakeLoop(start=0)
    _install_fake_loop(monkeypatch, module=workflows, loop=loop)

    dispatch_calls: list[tuple[str, str, str]] = []

    async def _fake_dispatch(full_name: str, workflow: str, ref: str, inputs=None):
        dispatch_calls.append((full_name, workflow, ref))

    async def _fake_wait(
        full_name: str, run_id: int, timeout_seconds=0, poll_interval_seconds=0
    ):
        return {
            "status": "completed",
            "conclusion": "success",
            "controller_log": ["done"],
        }

    monkeypatch.setattr(workflows, "trigger_workflow_dispatch", _fake_dispatch)
    monkeypatch.setattr(workflows, "wait_for_workflow_run", _fake_wait)

    # First poll: no runs. Second poll: include multiple candidates.
    fake.queue_list_workflow_runs(
        {"json": {"workflow_runs": []}},
        {
            "json": {
                "workflow_runs": [
                    # Wrong workflow file.
                    {
                        "id": 1,
                        "event": "workflow_dispatch",
                        "path": ".github/workflows/other.yml",
                        "created_at": "2099-01-01T00:00:00Z",
                    },
                    # Older matching run.
                    {
                        "id": 2,
                        "event": "workflow_dispatch",
                        "path": ".github/workflows/ci.yml",
                        "created_at": "2098-01-01T00:00:00Z",
                    },
                    # Newer matching run.
                    {
                        "id": 3,
                        "event": "workflow_dispatch",
                        "path": ".github/workflows/ci.yml",
                        "created_at": "2099-01-01T00:00:00Z",
                    },
                ]
            }
        },
    )

    sha_ref = "a" * 40
    out = await workflows.trigger_and_wait_for_workflow(
        "o/r",
        workflow=".github/workflows/ci.yml",
        ref=sha_ref,
        inputs={"x": 1},
        timeout_seconds=10,
        poll_interval_seconds=1,
    )

    assert dispatch_calls == [("o/r", ".github/workflows/ci.yml", sha_ref)]

    # Branch filter should be None for a SHA.
    assert fake._list_runs_calls[0]["branch"] is None

    assert out["run_id"] == 3
    log = "\n".join(out["controller_log"])
    assert "Triggered workflow and waited" in log
    assert "Run ID: 3" in log


@pytest.mark.asyncio
async def test_trigger_and_wait_for_workflow_raises_when_no_run_found(monkeypatch):
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.main_tools import workflows

    fake = FakeMain()
    monkeypatch.setattr(workflows, "_main", lambda: fake)

    loop = FakeLoop(start=0)
    _install_fake_loop(monkeypatch, module=workflows, loop=loop)

    async def _fake_dispatch(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workflows, "trigger_workflow_dispatch", _fake_dispatch)

    # Always returns no runs; loop will advance by 2 seconds each sleep and eventually exceed deadline.
    fake.queue_list_workflow_runs(*({"json": {"workflow_runs": []}} for _ in range(40)))

    with pytest.raises(GitHubAPIError):
        await workflows.trigger_and_wait_for_workflow(
            "o/r",
            workflow="ci.yml",
            ref="main",
            timeout_seconds=10,
            poll_interval_seconds=1,
        )

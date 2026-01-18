from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from github_mcp.main_tools import workflows
from github_mcp.utils import _decode_zipped_job_logs


def test_decode_zipped_job_logs_reports_errors() -> None:
    result = _decode_zipped_job_logs(b"not-a-zip")

    assert result
    assert result.startswith("[error decoding job logs archive:")


def test_get_job_logs_uses_fallback_client_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _noop_semaphore() -> None:
        yield

    dummy = SimpleNamespace(
        _get_concurrency_semaphore=_noop_semaphore,
        _decode_zipped_job_logs=_decode_zipped_job_logs,
    )

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "application/zip"}
        content = b"not-a-zip"
        text = "not-a-zip"

    class DummyClient:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def build_request(self, method: str, url: str, headers: dict[str, str]) -> dict[str, str]:
            request = {"method": method, "url": url, "headers": headers}
            self.requests.append(request)
            return request

        async def send(self, request: object, follow_redirects: bool = True) -> DummyResponse:
            self.requests.append({"send": follow_redirects, "request": request})
            return DummyResponse()

    created: dict[str, int] = {"count": 0}

    def _fake_factory() -> DummyClient:
        created["count"] += 1
        return DummyClient()

    monkeypatch.setattr(workflows, "_main", lambda: dummy)
    monkeypatch.setattr("github_mcp.http_clients._github_client_instance", _fake_factory)

    result = asyncio.run(workflows.get_job_logs("octo/repo", 123))

    assert created["count"] == 1
    assert result["status_code"] == 200
    assert result["content_type"] == "application/zip"
    assert "error decoding job logs archive" in result["logs"]

import httpx
import pytest

import main


class DummyResponse:
    def __init__(self, status_code=200, headers=None, json_data=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class DummyClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def request(self, method, path, params=None, json=None, headers=None):
        if self._exc is not None:
            raise self._exc
        return self._response


def _github_metrics():
    return main._METRICS.get("github", {})


def _tool_metrics(tool_name: str):
    tools_bucket = main._METRICS.get("tools", {})
    return tools_bucket.get(tool_name, {})


def test_tool_metrics_success_records_calls_and_latency():
    main._reset_metrics_for_tests()

    @main.mcp_tool(name="test_metric_tool_success", write_action=True)
    def tool_success():
        return "ok"

    result = tool_success()
    assert result == "ok"

    metrics = _tool_metrics("test_metric_tool_success")
    assert metrics.get("calls_total") == 1
    assert metrics.get("errors_total") == 0
    assert metrics.get("write_calls_total") == 1
    assert metrics.get("latency_ms_sum") >= 0


def test_tool_metrics_error_records_errors_and_write_calls():
    main._reset_metrics_for_tests()

    @main.mcp_tool(name="test_metric_tool_error", write_action=True)
    def tool_error():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        tool_error()

    metrics = _tool_metrics("test_metric_tool_error")
    assert metrics.get("calls_total") == 1
    assert metrics.get("errors_total") == 1
    assert metrics.get("write_calls_total") == 1
    assert metrics.get("latency_ms_sum") >= 0


@pytest.mark.asyncio
async def test_github_metrics_success(monkeypatch):
    main._reset_metrics_for_tests()

    response = DummyResponse(
        status_code=200,
        headers={
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "10",
            "X-RateLimit-Reset": "123456",
        },
        json_data={"ok": True},
        text="ok",
    )
    client = DummyClient(response=response)
    monkeypatch.setattr(main, "_github_client_instance", lambda: client)

    result = await main._github_request("GET", "/dummy/path")

    assert result["status_code"] == 200
    metrics = _github_metrics()
    assert metrics.get("requests_total") == 1
    assert metrics.get("errors_total") == 0
    assert metrics.get("rate_limit_events_total") == 0
    assert metrics.get("timeouts_total") == 0


@pytest.mark.asyncio
async def test_github_metrics_http_error(monkeypatch):
    main._reset_metrics_for_tests()

    response = DummyResponse(
        status_code=500,
        headers={
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "10",
            "X-RateLimit-Reset": "123456",
        },
        json_data={"message": "Internal error"},
        text="Internal error",
    )
    client = DummyClient(response=response)
    monkeypatch.setattr(main, "_github_client_instance", lambda: client)

    with pytest.raises(main.GitHubAPIError):
        await main._github_request("GET", "/dummy/path")

    metrics = _github_metrics()
    assert metrics.get("requests_total") == 1
    assert metrics.get("errors_total") == 1
    assert metrics.get("rate_limit_events_total") == 0
    assert metrics.get("timeouts_total") == 0


@pytest.mark.asyncio
async def test_github_metrics_rate_limit_event(monkeypatch):
    main._reset_metrics_for_tests()

    response = DummyResponse(
        status_code=200,
        headers={
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "123456",
        },
        json_data={"ok": True},
        text="ok",
    )
    client = DummyClient(response=response)
    monkeypatch.setattr(main, "_github_client_instance", lambda: client)

    result = await main._github_request("GET", "/dummy/path")

    assert result["status_code"] == 200
    metrics = _github_metrics()
    assert metrics.get("requests_total") == 1
    assert metrics.get("errors_total") == 0
    assert metrics.get("rate_limit_events_total") == 1
    assert metrics.get("timeouts_total") == 0


@pytest.mark.asyncio
async def test_github_metrics_timeout(monkeypatch):
    main._reset_metrics_for_tests()

    timeout_exc = httpx.TimeoutException("boom")
    client = DummyClient(response=None, exc=timeout_exc)
    monkeypatch.setattr(main, "_github_client_instance", lambda: client)

    with pytest.raises(httpx.TimeoutException):
        await main._github_request("GET", "/dummy/path")

    metrics = _github_metrics()
    assert metrics.get("requests_total") == 1
    assert metrics.get("errors_total") == 1
    assert metrics.get("rate_limit_events_total") == 0
    assert metrics.get("timeouts_total") == 1

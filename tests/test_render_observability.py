from __future__ import annotations

from typing import Any, Dict

import pytest

import github_mcp.main_tools.render_observability as ro
from github_mcp.exceptions import UsageError


@pytest.mark.asyncio
async def test_list_render_logs_builds_expected_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    async def fake_get(path: str, *, params: Dict[str, Any]) -> Any:
        captured["path"] = path
        captured["params"] = dict(params)
        return {"ok": True}

    monkeypatch.setattr(ro, "_render_get", fake_get)

    await ro.list_render_logs(
        ownerId="own-1",
        resource=["srv-1", "srv-2"],
        level=["info"],
        type=["app"],
        text=["error"],
        startTime="2025-01-01T00:00:00Z",
        endTime="2025-01-02T00:00:00Z",
        direction="backward",
        limit=50,
    )

    assert captured["path"] == "/logs"
    assert captured["params"]["ownerId"] == "own-1"
    assert captured["params"]["resource"] == "srv-1,srv-2"
    assert captured["params"]["level"] == "info"
    assert captured["params"]["type"] == "app"
    assert captured["params"]["text"] == "error"
    assert captured["params"]["limit"] == 50


@pytest.mark.asyncio
async def test_get_render_metrics_rejects_unknown_metric_types() -> None:
    with pytest.raises(UsageError):
        await ro.get_render_metrics(metricTypes=["not_a_metric"], resourceId="srv-1")


@pytest.mark.asyncio
async def test_get_render_metrics_calls_expected_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_get(path: str, *, params: Dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        return {"ok": True, "path": path, "params": dict(params)}

    monkeypatch.setattr(ro, "_render_get", fake_get)

    out = await ro.get_render_metrics(
        metricTypes=["cpu_usage", "http_latency", "http_request_count"], resourceId="srv-1"
    )

    assert out["resourceId"] == "srv-1"
    assert set(out["metrics"].keys()) == {"cpu_usage", "http_latency", "http_request_count"}

    paths = [c[0] for c in calls]
    assert "/metrics/cpu" in paths
    assert "/metrics/http-latency" in paths
    assert "/metrics/http-requests" in paths

    # http-latency should include a quantile (default p95)
    latency_call = [c for c in calls if c[0] == "/metrics/http-latency"][0]
    assert latency_call[1]["quantile"] == "0.95"

from __future__ import annotations

from typing import Any, Dict

import pytest

import github_mcp.main_tools.render_observability as ro


@pytest.mark.asyncio
async def test_list_render_logs_builds_expected_query_params(monkeypatch: pytest.MonkeyPatch):
    captured: Dict[str, Any] = {}

    async def fake_get(path: str, *, params: Dict[str, Any]) -> Any:
        captured['path'] = path
        captured['params'] = params
        return {'ok': True}

    monkeypatch.setattr(ro, '_render_get', fake_get)

    await ro.list_render_logs(
        resource=['srv-1', 'srv-2'],
        level=['info'],
        type=['app'],
        text=['error'],
        startTime='2025-01-01T00:00:00Z',
        endTime='2025-01-02T00:00:00Z',
        direction='backward',
        limit=50,
    )

    assert captured['path'] == '/logs'
    assert captured['params']['resource'] == 'srv-1,srv-2'
    assert captured['params']['level'] == 'info'
    assert captured['params']['type'] == 'app'
    assert captured['params']['text'] == 'error'
    assert captured['params']['limit'] == 50


@pytest.mark.asyncio
async def test_get_render_metrics_rejects_unknown_metric_types():
    with pytest.raises(Exception):
        await ro.get_render_metrics(resourceId='srv-1', metricTypes=['not_a_metric'])

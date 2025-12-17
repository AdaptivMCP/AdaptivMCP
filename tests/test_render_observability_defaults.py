import inspect
from typing import Any, Dict

import pytest

import main

from github_mcp.exceptions import UsageError
import github_mcp.main_tools.render_observability as ro


@pytest.mark.asyncio
async def test_get_render_metrics_defaults_to_env_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, Any] = {}

    async def fake_render_get(path: str, *, params: Dict[str, Any]) -> Any:
        called["path"] = path
        called["params"] = dict(params)
        return {"ok": True}

    monkeypatch.setattr(ro, "_render_get", fake_render_get)
    monkeypatch.setattr(ro, "RENDER_DEFAULT_RESOURCE", "srv-123")

    out = await ro.get_render_metrics(resourceId=None, metricTypes=["cpu_usage"])

    assert called["path"] == ro._METRIC_ENDPOINTS["cpu_usage"]
    assert called["params"]["resource"] == "srv-123"
    assert out["resourceId"] == "srv-123"
    assert out["metrics"]["cpu_usage"] == {"ok": True}


@pytest.mark.asyncio
async def test_get_render_metrics_requires_resource_when_no_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ro, "RENDER_DEFAULT_RESOURCE", None)

    with pytest.raises(UsageError):
        await ro.get_render_metrics(resourceId=None, metricTypes=["cpu_usage"])


def test_main_tool_signature_resource_optional() -> None:
    sig = inspect.signature(main.get_render_metrics)
    assert sig.parameters["resourceId"].default is None

from typing import Any, Dict

import pytest

import github_mcp.main_tools.render_observability as ro
from github_mcp.exceptions import UsageError


@pytest.mark.asyncio
async def test_list_render_logs_resolves_owner_from_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Dict[str, Any]]] = []

    async def fake_render_get(path: str, *, params: Dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        if path.startswith("/services/"):
            return {"ownerId": "own-abc"}
        if path == "/logs":
            return [{"msg": "ok"}]
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(ro, "_render_get", fake_render_get)
    monkeypatch.setattr(ro, "RENDER_DEFAULT_RESOURCE", "srv-123")
    monkeypatch.setattr(ro, "RENDER_OWNER_ID", None)
    # clear cache
    monkeypatch.setattr(ro, "_OWNER_ID_CACHE", None)
    monkeypatch.setattr(ro, "_OWNER_ID_CACHE_AT", 0.0)

    out = await ro.list_render_logs(limit=1)
    assert out == [{"msg": "ok"}]

    # First call: service lookup
    assert calls[0][0] == "/services/srv-123"
    # Second call: logs, with ownerId
    assert calls[1][0] == "/logs"
    assert calls[1][1]["ownerId"] == "own-abc"
    assert calls[1][1]["resource"] == "srv-123"


@pytest.mark.asyncio
async def test_list_render_logs_uses_env_ownerid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Dict[str, Any]]] = []

    async def fake_render_get(path: str, *, params: Dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        if path == "/logs":
            return []
        raise AssertionError("service lookup should not happen")

    monkeypatch.setattr(ro, "_render_get", fake_render_get)
    monkeypatch.setattr(ro, "RENDER_DEFAULT_RESOURCE", "srv-123")
    monkeypatch.setattr(ro, "RENDER_OWNER_ID", "own-env")

    await ro.list_render_logs(limit=1)

    assert len(calls) == 1
    assert calls[0][0] == "/logs"
    assert calls[0][1]["ownerId"] == "own-env"
    assert calls[0][1]["resource"] == "srv-123"


@pytest.mark.asyncio
async def test_list_render_logs_requires_owner_or_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ro, "RENDER_DEFAULT_RESOURCE", None)
    monkeypatch.setattr(ro, "RENDER_OWNER_ID", None)

    with pytest.raises(UsageError):
        await ro.list_render_logs(limit=1)

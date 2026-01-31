from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from github_mcp.main_tools import render as render_tools


def test_unwrap_json_payload_best_effort() -> None:
    assert render_tools._unwrap_json_payload({"json": {"a": 1}}) == {"a": 1}
    assert render_tools._unwrap_json_payload({"json": 123, "status_code": 200}) == 123
    # Too many keys -> treated as not a wrapper.
    payload = {"json": {"a": 1}, "a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    assert render_tools._unwrap_json_payload(payload) is payload
    assert render_tools._unwrap_json_payload([1, 2, 3]) == [1, 2, 3]


def test_normalize_direction() -> None:
    assert render_tools._normalize_direction(None) == "backward"
    assert render_tools._normalize_direction("") == "backward"
    assert render_tools._normalize_direction(" Forward ") == "forward"
    assert render_tools._normalize_direction("BACKWARD") == "backward"
    with pytest.raises(TypeError):
        render_tools._normalize_direction(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_tools._normalize_direction("sideways")


def test_normalize_optional_str() -> None:
    assert render_tools._normalize_optional_str(None) is None
    assert render_tools._normalize_optional_str("   ") is None
    assert render_tools._normalize_optional_str(" x ") == "x"
    with pytest.raises(TypeError):
        render_tools._normalize_optional_str(1)  # type: ignore[arg-type]


def test_require_non_empty_helpers() -> None:
    assert render_tools._require_non_empty_str("x", "  hi ") == "hi"
    with pytest.raises(ValueError):
        render_tools._require_non_empty_str("x", "  ")
    with pytest.raises(ValueError):
        render_tools._require_non_empty_str("x", None)  # type: ignore[arg-type]

    assert render_tools._require_non_empty_dict("x", {"a": 1}) == {"a": 1}
    with pytest.raises(ValueError):
        render_tools._require_non_empty_dict("x", {})
    with pytest.raises(ValueError):
        render_tools._require_non_empty_dict("x", [])  # type: ignore[arg-type]


def test_normalize_limit() -> None:
    assert (
        render_tools._normalize_limit(None, default=20, min_value=1, max_value=100)
        == 20
    )
    assert (
        render_tools._normalize_limit(" 7 ", default=20, min_value=1, max_value=100)
        == 7
    )
    assert render_tools._normalize_limit(0, default=20, min_value=1, max_value=100) == 1
    assert (
        render_tools._normalize_limit(999, default=20, min_value=1, max_value=100)
        == 100
    )
    with pytest.raises(TypeError):
        render_tools._normalize_limit(True, default=20, min_value=1, max_value=100)
    with pytest.raises(TypeError):
        render_tools._normalize_limit("nope", default=20, min_value=1, max_value=100)


def test_parse_iso8601_and_normalize_iso8601() -> None:
    dt = render_tools._parse_iso8601("2026-01-14T12:34:56Z", name="ts")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None

    # Naive timestamps are treated as UTC.
    naive = render_tools._parse_iso8601("2026-01-14T12:34:56", name="ts")
    assert naive.tzinfo is not None

    assert (
        render_tools._normalize_iso8601("2026-01-14T12:34:56Z", name="ts")
        == "2026-01-14T12:34:56Z"
    )
    assert render_tools._normalize_iso8601(None, name="ts") is None
    with pytest.raises(ValueError):
        render_tools._parse_iso8601("", name="ts")
    with pytest.raises(ValueError):
        render_tools._parse_iso8601("not-a-date", name="ts")


@pytest.mark.anyio
async def test_create_render_deploy_body_is_omitted_when_no_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        observed.update(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return {"status_code": 201, "json": {"ok": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    resp = await render_tools.create_render_deploy(service_id="svc")
    assert resp["json"]["ok"] is True
    assert observed["method"] == "POST"
    assert observed["path"] == "/services/svc/deploys"
    assert observed["json_body"] is None


@pytest.mark.anyio
async def test_create_render_deploy_body_includes_selected_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        observed["json_body"] = json_body
        return {"status_code": 201, "json": {"ok": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    await render_tools.create_render_deploy(service_id="svc", clear_cache=True)
    assert observed["json_body"] == {"clearCache": True}

    await render_tools.create_render_deploy(service_id="svc", commit_id="deadbeef")
    assert observed["json_body"] == {"commitId": "deadbeef"}

    await render_tools.create_render_deploy(service_id="svc", image_url="img")
    assert observed["json_body"] == {"imageUrl": "img"}

    with pytest.raises(ValueError, match="only one of commit_id or image_url"):
        await render_tools.create_render_deploy(
            service_id="svc", commit_id="a", image_url="b"
        )


@pytest.mark.anyio
async def test_list_render_logs_validates_and_builds_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        observed.update(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return {"status_code": 200, "json": {"lines": []}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    resp = await render_tools.list_render_logs(
        owner_id="owner",
        resources=[" r1 ", "r2"],
        start_time="2026-01-14T00:00:00Z",
        end_time="2026-01-14T01:00:00Z",
        direction="forward",
        limit=5000,
        instance="i",
        host="h",
        level="info",
        method="GET",
        status_code=200,
        path="/x",
        text="needle",
        log_type="app",
    )

    assert resp["status_code"] == 200
    assert observed["method"] == "GET"
    assert observed["path"] == "/logs"
    params = observed["params"]
    assert params["ownerId"] == "owner"
    assert params["resource"] == ["r1", "r2"]
    assert params["direction"] == "forward"
    # limit is clamped to 1000
    assert params["limit"] == 1000
    assert params["startTime"].endswith("Z")
    assert params["endTime"].endswith("Z")
    assert params["statusCode"] == 200
    assert params["logType"] == "app"

    with pytest.raises(ValueError, match="resources must be a non-empty"):
        await render_tools.list_render_logs(owner_id="owner", resources=[])

    with pytest.raises(ValueError, match=r"resources\[0\]"):
        await render_tools.list_render_logs(owner_id="owner", resources=[""])

    with pytest.raises(ValueError, match="start_time must be <= end_time"):
        await render_tools.list_render_logs(
            owner_id="owner",
            resources=["r"],
            start_time="2026-01-15T00:00:00Z",
            end_time="2026-01-14T00:00:00Z",
        )

    with pytest.raises(TypeError, match="status_code must be an integer"):
        await render_tools.list_render_logs(
            owner_id="owner", resources=["r"], status_code=True
        )


@pytest.mark.anyio
async def test_list_render_endpoints_build_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        calls.append(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return {"status_code": 200, "json": {"ok": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    await render_tools.list_render_owners(cursor="  c ", limit=0)
    assert calls[-1]["path"] == "/owners"
    assert calls[-1]["params"]["limit"] == 1
    assert calls[-1]["params"]["cursor"] == "c"

    await render_tools.list_render_services(owner_id="  o ", cursor=None, limit=999)
    assert calls[-1]["path"] == "/services"
    assert calls[-1]["params"]["limit"] == 100
    assert calls[-1]["params"]["ownerId"] == "o"

    await render_tools.list_render_deploys(service_id="svc", cursor="x", limit="10")
    assert calls[-1]["path"] == "/services/svc/deploys"
    assert calls[-1]["params"]["cursor"] == "x"
    assert calls[-1]["params"]["limit"] == 10


@pytest.mark.anyio
async def test_simple_render_service_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        calls.append(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return {"status_code": 200, "json": {"ok": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    await render_tools.get_render_service("svc")
    assert calls[-1]["path"] == "/services/svc"

    await render_tools.get_render_deploy("svc", "dep")
    assert calls[-1]["path"] == "/services/svc/deploys/dep"

    await render_tools.cancel_render_deploy("svc", "dep")
    assert calls[-1]["path"].endswith("/cancel")

    await render_tools.rollback_render_deploy("svc", "dep")
    assert calls[-1]["path"].endswith("/rollback")

    await render_tools.restart_render_service("svc")
    assert calls[-1]["path"] == "/services/svc/restart"


@pytest.mark.anyio
async def test_env_var_and_patch_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake(method: str, path: str, *, params=None, json_body=None):
        calls.append(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return {"status_code": 200, "json": {"ok": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    await render_tools.list_render_service_env_vars("svc")
    assert calls[-1]["path"] == "/services/svc/env-vars"

    with pytest.raises(ValueError, match="env_vars must be a non-empty"):
        await render_tools.set_render_service_env_vars("svc", [])
    with pytest.raises(ValueError, match=r"env_vars\[0\]"):
        await render_tools.set_render_service_env_vars("svc", [{}])
    await render_tools.set_render_service_env_vars("svc", [{"key": "A", "value": "B"}])
    assert calls[-1]["method"] == "PUT"
    assert calls[-1]["json_body"] == [{"key": "A", "value": "B"}]

    with pytest.raises(ValueError, match="patch must be a non-empty"):
        await render_tools.patch_render_service("svc", {})
    await render_tools.patch_render_service("svc", {"name": "x"})
    assert calls[-1]["method"] == "PATCH"
    assert calls[-1]["json_body"] == {"name": "x"}


@pytest.mark.anyio
async def test_create_render_service_requires_non_empty_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake(method: str, path: str, *, params=None, json_body=None):
        return {"status_code": 201, "json": {"spec": json_body}, "headers": {}}

    monkeypatch.setattr(render_tools, "render_request", _fake)

    with pytest.raises(ValueError, match="service_spec must be a non-empty"):
        await render_tools.create_render_service({})
    resp = await render_tools.create_render_service({"type": "web"})
    assert resp["json"]["spec"] == {"type": "web"}


@pytest.mark.anyio
async def test_get_render_logs_service_resolves_owner_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_service(service_id: str):
        assert service_id == "svc"
        return {"status_code": 200, "json": {"ownerId": "own"}, "headers": {}}

    observed: dict[str, Any] = {}

    async def _fake_list_logs(**kwargs: Any):
        observed.update(kwargs)
        return {"status_code": 200, "json": {"lines": ["x"]}, "headers": {}}

    monkeypatch.setattr(render_tools, "get_render_service", _fake_get_service)
    monkeypatch.setattr(render_tools, "list_render_logs", _fake_list_logs)

    resp = await render_tools.get_render_logs(
        "service",
        "svc",
        start_time="2026-01-14T00:00:00Z",
        end_time="2026-01-14T00:01:00Z",
        limit=5,
    )
    assert resp["json"]["lines"] == ["x"]
    assert observed["owner_id"] == "own"
    assert observed["resources"] == ["svc"]
    assert observed["limit"] == 5


@pytest.mark.anyio
async def test_get_render_logs_service_missing_owner_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_service(service_id: str):
        return {"status_code": 200, "json": {"nope": True}, "headers": {}}

    monkeypatch.setattr(render_tools, "get_render_service", _fake_get_service)

    with pytest.raises(ValueError, match="Unable to resolve ownerId"):
        await render_tools.get_render_logs("service", "svc")


@pytest.mark.anyio
async def test_get_render_logs_rejects_job_without_owner_id() -> None:
    with pytest.raises(ValueError, match="require owner_id"):
        await render_tools.get_render_logs("job", "job-1")

    with pytest.raises(ValueError, match="resource_type must be one of"):
        await render_tools.get_render_logs("other", "x")

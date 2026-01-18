from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_list_render_service_env_vars_calls_expected_endpoint(monkeypatch):
    import github_mcp.main_tools.render as render_tools

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    observed: dict = {}

    async def fake_request(method, path, **kwargs):
        observed["method"] = method
        observed["path"] = path
        observed["kwargs"] = kwargs
        return {"status_code": 200, "json": []}

    monkeypatch.setattr(render_tools, "render_request", fake_request)

    result = await render_tools.list_render_service_env_vars("srv_123")
    assert result["status_code"] == 200
    assert observed["method"] == "GET"
    assert observed["path"] == "/services/srv_123/env-vars"


@pytest.mark.anyio
async def test_set_render_service_env_vars_puts_list_body(monkeypatch):
    import github_mcp.main_tools.render as render_tools

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    observed: dict = {}

    async def fake_request(method, path, **kwargs):
        observed["method"] = method
        observed["path"] = path
        observed["kwargs"] = kwargs
        return {"status_code": 200, "json": {"ok": True}}

    monkeypatch.setattr(render_tools, "render_request", fake_request)

    env_vars = [{"key": "FOO", "value": "bar"}]
    result = await render_tools.set_render_service_env_vars("srv_123", env_vars)
    assert result["status_code"] == 200
    assert observed["method"] == "PUT"
    assert observed["path"] == "/services/srv_123/env-vars"
    assert observed["kwargs"]["json_body"] == env_vars


@pytest.mark.anyio
async def test_patch_render_service_patches_dict_body(monkeypatch):
    import github_mcp.main_tools.render as render_tools

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    observed: dict = {}

    async def fake_request(method, path, **kwargs):
        observed["method"] = method
        observed["path"] = path
        observed["kwargs"] = kwargs
        return {"status_code": 200, "json": {"updated": True}}

    monkeypatch.setattr(render_tools, "render_request", fake_request)

    patch = {"name": "new-name"}
    result = await render_tools.patch_render_service("srv_123", patch)
    assert result["status_code"] == 200
    assert observed["method"] == "PATCH"
    assert observed["path"] == "/services/srv_123"
    assert observed["kwargs"]["json_body"] == patch


@pytest.mark.anyio
async def test_set_render_service_env_vars_rejects_empty_list(monkeypatch):
    import github_mcp.main_tools.render as render_tools

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    with pytest.raises(ValueError):
        await render_tools.set_render_service_env_vars("srv_123", [])


@pytest.mark.anyio
async def test_patch_render_service_rejects_empty_patch(monkeypatch):
    import github_mcp.main_tools.render as render_tools

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    with pytest.raises(ValueError):
        await render_tools.patch_render_service("srv_123", {})

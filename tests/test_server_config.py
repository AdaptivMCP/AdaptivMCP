from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from github_mcp.exceptions import GitHubAPIError, GitHubAuthError
from github_mcp.main_tools import server_config


def test_get_server_config_env_flags(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_123")
    monkeypatch.setenv("RENDER_API_KEY", "render-token")
    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "0")

    payload = asyncio.run(server_config.get_server_config())

    assert payload["environment"]["github_token_present"] is True
    assert payload["environment"]["render_token_present"] is True
    assert payload["write_allowed"] is False


def test_get_repo_defaults_uses_controller_branch(monkeypatch):
    fake_main = SimpleNamespace(
        CONTROLLER_REPO="octo/controller",
        CONTROLLER_DEFAULT_BRANCH="stable",
    )
    monkeypatch.setitem(sys.modules, "main", fake_main)

    async def _guard_request(*args, **kwargs):
        raise AssertionError("_github_request should not be called")

    monkeypatch.setattr(server_config, "_github_request", _guard_request)
    monkeypatch.setattr(
        server_config,
        "REPO_DEFAULTS",
        {"octo/controller": {"default_branch": "main"}},
    )

    result = asyncio.run(server_config.get_repo_defaults())

    assert result["full_name"] == "octo/controller"
    assert result["default_branch"] == "stable"
    assert result["defaults"]["default_branch"] == "main"


def test_get_repo_defaults_fetches_branch(monkeypatch):
    async def _fake_request(method, path):
        assert method == "GET"
        assert path == "/repos/octo/other"
        return {"json": {"default_branch": "release"}}

    monkeypatch.setattr(server_config, "_github_request", _fake_request)
    monkeypatch.setattr(server_config, "REPO_DEFAULTS", {})

    result = asyncio.run(server_config.get_repo_defaults("octo/other"))

    assert result["default_branch"] == "release"


def test_get_repo_defaults_handles_bad_repo_payload(monkeypatch):
    async def _fake_request(method, path):
        assert method == "GET"
        assert path == "/repos/octo/other"
        return {"json": ["not-a-dict"]}

    monkeypatch.setattr(server_config, "_github_request", _fake_request)
    monkeypatch.setattr(server_config, "REPO_DEFAULTS", {})

    result = asyncio.run(server_config.get_repo_defaults("octo/other"))

    assert result["default_branch"] == "main"


def test_get_repo_defaults_handles_auth_error(monkeypatch):
    async def _fake_request(method, path):
        raise GitHubAuthError("missing")

    monkeypatch.setattr(server_config, "_github_request", _fake_request)
    monkeypatch.setattr(server_config, "REPO_DEFAULTS", {})

    result = asyncio.run(server_config.get_repo_defaults("octo/other"))

    assert result["default_branch"] == "main"


def test_get_repo_defaults_handles_api_error(monkeypatch):
    async def _fake_request(method, path):
        raise GitHubAPIError("boom")

    monkeypatch.setattr(server_config, "_github_request", _fake_request)
    monkeypatch.setattr(server_config, "REPO_DEFAULTS", {})

    result = asyncio.run(server_config.get_repo_defaults("octo/other"))

    assert result["default_branch"] == "main"

from __future__ import annotations

import asyncio
from types import ModuleType

import pytest

from github_mcp.exceptions import GitHubAuthError


def test_get_user_login_falls_back_to_app(monkeypatch):
    from github_mcp.main_tools import repositories

    async def _github_request(method: str, path: str, **_kwargs):
        if method == "GET" and path == "/user":
            raise GitHubAuthError("Resource not accessible by integration")
        if method == "GET" and path == "/app":
            return {"status_code": 200, "json": {"slug": "sample-app", "name": "Sample App"}}
        raise AssertionError(f"Unexpected request: {method} {path}")

    dummy_main = ModuleType("main")
    dummy_main._github_request = _github_request

    monkeypatch.setattr(repositories, "_main", lambda: dummy_main)

    result = asyncio.run(repositories.get_user_login())

    assert result["login"] == "sample-app"
    assert result["user"] is None
    assert result["app"]["slug"] == "sample-app"
    assert result["account_type"] == "app"


def test_create_repository_template_org_skips_user_lookup(monkeypatch):
    from github_mcp.main_tools import repositories

    calls: list[tuple[str, str]] = []

    async def _github_request(method: str, path: str, **kwargs):
        calls.append((method, path))
        if path == "/user":
            raise AssertionError("Unexpected /user call for org template creation")
        if method == "POST" and path == "/repos/octo/template/generate":
            return {"status_code": 201, "json": {"full_name": "octo/new-repo"}}
        raise AssertionError(f"Unexpected request: {method} {path} {kwargs}")

    dummy_main = ModuleType("main")
    dummy_main._github_request = _github_request

    monkeypatch.setattr(repositories, "_main", lambda: dummy_main)

    result = asyncio.run(
        repositories.create_repository(
            name="new-repo",
            owner="octo",
            owner_type="org",
            template_full_name="octo/template",
        )
    )

    assert result["created"]["status_code"] == 201
    assert ("GET", "/user") not in calls


def test_create_repository_user_owner_blocks_app_tokens(monkeypatch):
    from github_mcp.main_tools import repositories

    async def _github_request(method: str, path: str, **_kwargs):
        if method == "GET" and path == "/user":
            raise GitHubAuthError("Resource not accessible by integration")
        if method == "GET" and path == "/app":
            return {"status_code": 200, "json": {"slug": "sample-app"}}
        raise AssertionError(f"Unexpected request: {method} {path}")

    dummy_main = ModuleType("main")
    dummy_main._github_request = _github_request
    dummy_main._structured_tool_error = (
        lambda exc, context=None: {"error": str(exc), "error_type": type(exc).__name__}
    )

    monkeypatch.setattr(repositories, "_main", lambda: dummy_main)

    result = asyncio.run(
        repositories.create_repository(
            name="new-repo",
            owner="octo",
            owner_type="user",
        )
    )

    assert result["error_type"] == "ValueError"
    assert "GitHub App tokens cannot create user repositories" in result["error"]

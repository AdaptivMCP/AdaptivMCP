from __future__ import annotations

from types import SimpleNamespace

import pytest


class DummyMainNoNetwork:
    CONTROLLER_REPO = "owner/repo"
    CONTROLLER_DEFAULT_BRANCH = "main"

    GITHUB_API_BASE = "https://api.github.com"
    HTTPX_TIMEOUT = 10.0
    HTTPX_MAX_CONNECTIONS = 10
    HTTPX_MAX_KEEPALIVE = 10

    MAX_CONCURRENCY = 10
    FETCH_FILES_CONCURRENCY = 5

    async def _github_request(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("_github_request should not be called when token is missing")


@pytest.mark.anyio
async def test_validate_environment_missing_tokens_marks_error(monkeypatch):
    import github_mcp.main_tools.env as env
    from github_mcp.config import GITHUB_TOKEN_ENV_VARS, RENDER_TOKEN_ENV_VARS

    # Force a deterministic "no token" environment even when running in CI.
    monkeypatch.setattr(env.sys, "version_info", SimpleNamespace(major=3, minor=12, micro=0))
    for name in GITHUB_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in RENDER_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(env, "_main", lambda: DummyMainNoNetwork())

    payload = await env.validate_environment()

    assert payload["status"] == "error"
    assert payload["summary"]["error"] >= 1

    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["github_token"]["level"] == "error"
    assert checks["controller_remote_checks"]["level"] == "warning"
    assert checks["render_token"]["level"] == "warning"


@pytest.mark.anyio
async def test_validate_environment_flags_unsupported_python(monkeypatch):
    import github_mcp.main_tools.env as env
    from github_mcp.config import GITHUB_TOKEN_ENV_VARS, RENDER_TOKEN_ENV_VARS

    monkeypatch.setattr(env.sys, "version_info", SimpleNamespace(major=3, minor=11, micro=9))
    for name in GITHUB_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in RENDER_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(env, "_main", lambda: DummyMainNoNetwork())

    payload = await env.validate_environment()

    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["python_version"]["level"] == "error"


class DummyMainAllGreen:
    CONTROLLER_REPO = "owner/repo"
    CONTROLLER_DEFAULT_BRANCH = "main"

    GITHUB_API_BASE = "https://api.github.com"
    HTTPX_TIMEOUT = 10.0
    HTTPX_MAX_CONNECTIONS = 10
    HTTPX_MAX_KEEPALIVE = 10

    MAX_CONCURRENCY = 10
    FETCH_FILES_CONCURRENCY = 5

    async def _github_request(
        self,
        method: str,
        path: str,
        *,
        params=None,
        json_body=None,
        expect_json: bool = True,
    ):
        from github_mcp.exceptions import GitHubAPIError

        repo = self.CONTROLLER_REPO
        branch = self.CONTROLLER_DEFAULT_BRANCH

        if method == "GET" and path == "/user":
            return {
                "headers": {"X-OAuth-Scopes": "repo, workflow"},
                "json": {"login": "dummy", "id": 1, "type": "User"},
            }

        if method == "GET" and path == "/rate_limit":
            return {
                "json": {
                    "resources": {
                        "core": {"limit": 5000, "used": 0, "remaining": 5000, "reset": 0},
                        "graphql": {"limit": 5000, "used": 0, "remaining": 5000, "reset": 0},
                        "search": {"limit": 30, "used": 0, "remaining": 30, "reset": 0},
                    }
                }
            }

        if method == "GET" and path == f"/repos/{repo}":
            return {"json": {"permissions": {"admin": True, "push": True, "pull": True}}}

        if method == "GET" and path == f"/repos/{repo}/actions/workflows":
            return {
                "json": {
                    "workflows": [
                        {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml"},
                    ]
                }
            }

        if method == "POST" and path == f"/repos/{repo}/pulls":
            # The env validator intentionally sends a bogus head so GitHub returns 422.
            raise GitHubAPIError("Validation Failed", status_code=422)

        if method == "POST" and path == f"/repos/{repo}/actions/workflows/1/dispatches":
            # Side-effectful in production, but no-op in tests.
            return {"status_code": 204, "json": None} if expect_json else {"status_code": 204}

        if method == "GET" and path == f"/repos/{repo}/actions/workflows/1/runs":
            return {"json": {"workflow_runs": [{"id": 123}]}}

        if method == "GET" and path == f"/repos/{repo}/branches/{branch}":
            return {"json": {"name": branch}}

        if method == "GET" and path == f"/repos/{repo}/pulls":
            return {"json": []}

        raise AssertionError(
            f"Unexpected request: {method} {path} params={params} json={json_body}"
        )


@pytest.mark.anyio
async def test_validate_environment_happy_path_ok(monkeypatch):
    import github_mcp.main_tools.env as env

    # Avoid identity placeholder warnings in this unit test.
    monkeypatch.setattr(env.sys, "version_info", SimpleNamespace(major=3, minor=12, micro=0))
    monkeypatch.setattr(env, "GIT_IDENTITY_PLACEHOLDER_ACTIVE", False)

    # Ensure the env tool registry sanity check does not fail due to import-order
    # subtleties in an isolated unit test environment.
    expected_tool_names = {
        # Introspection
        "list_all_actions",
        "list_tools",
        "describe_tool",
        # Render (canonical)
        "list_render_owners",
        "list_render_services",
        "get_render_service",
        "list_render_deploys",
        "get_render_deploy",
        "create_render_deploy",
        "cancel_render_deploy",
        "rollback_render_deploy",
        "restart_render_service",
        "get_render_logs",
        "list_render_logs",
        # Render (aliases)
        "render_list_owners",
        "render_list_services",
        "render_get_service",
        "render_list_deploys",
        "render_get_deploy",
        "render_create_deploy",
        "render_cancel_deploy",
        "render_rollback_deploy",
        "render_restart_service",
        "render_get_logs",
        "render_list_logs",
    }

    def fake_list_all_actions(*, include_parameters: bool = False, compact: bool | None = None):
        return {"tools": [{"name": name} for name in sorted(expected_tool_names)]}

    monkeypatch.setattr(
        "github_mcp.main_tools.introspection.list_all_actions",
        fake_list_all_actions,
    )
    monkeypatch.setattr(
        "github_mcp.mcp_server.registry._REGISTERED_MCP_TOOLS",
        [{"name": name} for name in sorted(expected_tool_names)],
    )

    from github_mcp.config import GITHUB_TOKEN_ENV_VARS

    # Ensure the token selection is deterministic even if the CI environment
    # has other (possibly empty) GitHub token variables set.
    for name in GITHUB_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    token_env = list(GITHUB_TOKEN_ENV_VARS)[0]
    monkeypatch.setenv(token_env, "test-token")

    # Force controller repo/branch config to match the dummy main object.
    monkeypatch.setenv("ADAPTIV_MCP_CONTROLLER_REPO", DummyMainAllGreen.CONTROLLER_REPO)
    monkeypatch.setenv("ADAPTIV_MCP_CONTROLLER_BRANCH", DummyMainAllGreen.CONTROLLER_DEFAULT_BRANCH)

    # The Render token helper is imported into env.py, so patch it there.
    monkeypatch.setattr(env, "_get_optional_render_token", lambda: "render-token")

    async def dummy_render_request(method: str, path: str, params=None, json_body=None):
        assert method == "GET"
        assert path == "/owners"
        return {"json": [{"id": "o1", "name": "Owner", "type": "team"}]}

    monkeypatch.setattr(env, "render_request", dummy_render_request)
    monkeypatch.setattr(env, "_main", lambda: DummyMainAllGreen())

    payload = await env.validate_environment()

    errors = [c for c in payload["checks"] if c.get("level") == "error"]
    assert not errors, {"errors": errors, "summary": payload.get("summary")}
    assert payload["status"] == "ok"


@pytest.mark.anyio
async def test_validate_environment_skips_empty_github_pat(monkeypatch):
    import github_mcp.main_tools.env as env

    # Avoid identity placeholder warnings in this unit test.
    monkeypatch.setattr(env.sys, "version_info", SimpleNamespace(major=3, minor=12, micro=0))
    monkeypatch.setattr(env, "GIT_IDENTITY_PLACEHOLDER_ACTIVE", False)

    expected_tool_names = {
        # Introspection
        "list_all_actions",
        "list_tools",
        "describe_tool",
        # Render (canonical)
        "list_render_owners",
        "list_render_services",
        "get_render_service",
        "list_render_deploys",
        "get_render_deploy",
        "create_render_deploy",
        "cancel_render_deploy",
        "rollback_render_deploy",
        "restart_render_service",
        "get_render_logs",
        "list_render_logs",
        # Render (aliases)
        "render_list_owners",
        "render_list_services",
        "render_get_service",
        "render_list_deploys",
        "render_get_deploy",
        "render_create_deploy",
        "render_cancel_deploy",
        "render_rollback_deploy",
        "render_restart_service",
        "render_get_logs",
        "render_list_logs",
    }

    def fake_list_all_actions(*, include_parameters: bool = False, compact: bool | None = None):
        return {"tools": [{"name": name} for name in sorted(expected_tool_names)]}

    monkeypatch.setattr(
        "github_mcp.main_tools.introspection.list_all_actions",
        fake_list_all_actions,
    )
    monkeypatch.setattr(
        "github_mcp.mcp_server.registry._REGISTERED_MCP_TOOLS",
        [{"name": name} for name in sorted(expected_tool_names)],
    )

    from github_mcp.config import GITHUB_TOKEN_ENV_VARS

    for name in GITHUB_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("GITHUB_PAT", "  ")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    monkeypatch.setenv("ADAPTIV_MCP_CONTROLLER_REPO", DummyMainAllGreen.CONTROLLER_REPO)
    monkeypatch.setenv("ADAPTIV_MCP_CONTROLLER_BRANCH", DummyMainAllGreen.CONTROLLER_DEFAULT_BRANCH)

    monkeypatch.setattr(env, "_get_optional_render_token", lambda: "render-token")

    async def dummy_render_request(method: str, path: str, params=None, json_body=None):
        assert method == "GET"
        assert path == "/owners"
        return {"json": [{"id": "o1", "name": "Owner", "type": "team"}]}

    monkeypatch.setattr(env, "render_request", dummy_render_request)
    monkeypatch.setattr(env, "_main", lambda: DummyMainAllGreen())

    payload = await env.validate_environment()

    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["github_token"]["level"] == "ok"
    assert checks["github_token"]["details"]["env_var"] == "GITHUB_TOKEN"


@pytest.mark.anyio
async def test_main_validate_environment_delegates(monkeypatch):
    import main

    sentinel = {"status": "ok", "checks": [], "summary": {"ok": 0, "warning": 0, "error": 0}}

    async def fake_impl():
        return sentinel

    monkeypatch.setattr("github_mcp.main_tools.env.validate_environment", fake_impl)

    # The tool decorator may wrap results; since PR #936 mapping returns include
    # tool metadata, validate the payload while allowing the additional field.
    out = await main.validate_environment()
    assert out["status"] == sentinel["status"]
    assert out["checks"] == sentinel["checks"]
    assert out["summary"] == sentinel["summary"]
    assert "gating" in out

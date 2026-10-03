from __future__ import annotations

import pytest

from github_mcp.mcp_server import transport_auth


def test_bearer_auth_is_constant_time_and_returns_principal(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_AUTH_TOKEN", "server-secret")
    monkeypatch.setenv("ADAPTIV_MCP_AUTH_CAPABILITIES", "workspace.write, git.push")

    ok, principal, capabilities = transport_auth.authenticate_request(
        [(b"authorization", b"Bearer server-secret")]
    )

    assert ok is True
    assert principal is not None
    assert principal.startswith("token:")
    assert "server-secret" not in principal
    assert capabilities == frozenset({"workspace.write", "git.push"})


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"authorization", b"Bearer wrong")],
        [(b"authorization", b"Basic server-secret")],
        [(b"x-openai-user-id", b"spoofed-user")],
    ],
)
def test_invalid_or_untrusted_headers_do_not_authenticate(monkeypatch, headers):
    monkeypatch.setenv("ADAPTIV_MCP_AUTH_TOKEN", "server-secret")

    ok, principal, capabilities = transport_auth.authenticate_request(headers)

    assert ok is False
    assert principal is None
    assert capabilities == frozenset()


def test_missing_server_credential_fails_closed(monkeypatch):
    monkeypatch.delenv("ADAPTIV_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    ok, principal, capabilities = transport_auth.authenticate_request(
        [(b"authorization", b"Bearer anything")]
    )

    assert ok is False
    assert principal is None
    assert capabilities == frozenset()
    assert transport_auth.auth_configuration_present() is False


@pytest.mark.anyio
async def test_transport_middleware_binds_and_clears_principal(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_AUTH_TOKEN", "server-secret")

    import main
    from github_mcp.mcp_server.context import (
        get_request_capabilities,
        get_request_context,
    )

    seen = []

    async def app(scope, receive, send):
        seen.append(get_request_context())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = main._TransportAuthMiddleware(app)

    async def call(headers, path="/messages"):
        sent = []

        async def send(message):
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": headers,
            },
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            send,
        )
        return sent

    unauthorized = await call([])
    assert unauthorized[0]["status"] == 401
    assert not seen

    monkeypatch.setenv("ADAPTIV_MCP_AUTH_CAPABILITIES", "workspace.write")
    authorized = await call([(b"authorization", b"Bearer server-secret")])
    assert authorized[0]["status"] == 200
    assert seen[-1]["authenticated"] is True
    assert seen[-1]["principal"].startswith("token:")
    assert get_request_capabilities() == frozenset({"workspace.write"})

    public = await call([], path="/healthz")
    assert public[0]["status"] == 200
    assert seen[-1]["authenticated"] is False
    assert seen[-1]["principal"] is None
    assert get_request_capabilities() == frozenset()


def test_application_wires_transport_auth_and_trusted_host_middleware(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_AUTH_TOKEN", "server-secret")
    import main

    assert main.app is not None
    middleware_names = [m.cls.__name__ for m in main.app.user_middleware]
    assert "_TransportAuthMiddleware" in middleware_names
    assert "TrustedHostMiddleware" in middleware_names

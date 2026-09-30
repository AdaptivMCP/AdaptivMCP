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

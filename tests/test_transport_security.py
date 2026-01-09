import importlib
import sys

import pytest

pytest.importorskip("mcp.server.transport_security")


def _reload_context() -> object:
    sys.modules.pop("github_mcp.mcp_server.context", None)
    return importlib.import_module("github_mcp.mcp_server.context")


def _assert_host_allowed(settings, host: str) -> None:
    allowed_hosts = settings.allowed_hosts
    assert any(value == host or value.startswith(f"{host}:") for value in allowed_hosts)


def test_transport_security_includes_render_host(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "chatgpt-mcp-github-iu2y.onrender.com")

    context = _reload_context()
    settings = context.mcp.settings.transport_security

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    _assert_host_allowed(settings, "localhost")
    _assert_host_allowed(settings, "chatgpt-mcp-github-iu2y.onrender.com")


def test_transport_security_disabled_when_wildcard_allowed(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "*")

    context = _reload_context()
    settings = context.mcp.settings.transport_security

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is False

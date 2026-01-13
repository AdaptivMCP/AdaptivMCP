import importlib
import sys

import pytest

pytest.importorskip("mcp.server.transport_security")


def _reload_context() -> object:
    sys.modules.pop("github_mcp.mcp_server.context", None)
    return importlib.import_module("github_mcp.mcp_server.context")


def test_transport_security_configured_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "chatgpt-mcp-github-iu2y.onrender.com")

    context = _reload_context()
    settings = context.mcp.settings.transport_security

    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True
    assert "localhost" in settings.allowed_hosts
    assert "localhost:*" in settings.allowed_hosts
    assert "chatgpt-mcp-github-iu2y.onrender.com" in settings.allowed_hosts
    assert "https://chatgpt-mcp-github-iu2y.onrender.com" in settings.allowed_origins

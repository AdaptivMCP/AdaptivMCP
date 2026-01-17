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

    # This server intentionally disables FastMCP transport security enforcement
    # (allowed hosts/origins, DNS rebinding protection) because it is commonly
    # deployed behind a trusted reverse proxy and enforces authorization at the
    # tool layer. The env vars may still be set in hosted environments, but the
    # server must not construct transport security settings.
    assert settings is None

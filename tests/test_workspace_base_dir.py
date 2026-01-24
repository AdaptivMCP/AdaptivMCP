import os
import tempfile

from github_mcp import config


def test_default_workspace_base_dir_uses_xdg_cache_home(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/cache-root")
    assert (
        config._default_workspace_base_dir() == "/tmp/cache-root/mcp-github-workspaces"
    )


def test_default_workspace_base_dir_falls_back_to_tmp(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda _: "~")
    expected = os.path.join(tempfile.gettempdir(), "mcp-github-workspaces")
    assert config._default_workspace_base_dir() == expected

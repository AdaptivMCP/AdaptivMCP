from __future__ import annotations

import importlib


def _reload_config(monkeypatch, env: dict[str, str | None]):
    import github_mcp.config as config

    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    return importlib.reload(config)


def test_git_identity_ignores_whitespace_env(monkeypatch):
    config = _reload_config(
        monkeypatch,
        {
            "ADAPTIV_MCP_GIT_AUTHOR_NAME": "   ",
            "ADAPTIV_MCP_GIT_AUTHOR_EMAIL": "\t",
            "ADAPTIV_MCP_GIT_COMMITTER_NAME": " ",
            "ADAPTIV_MCP_GIT_COMMITTER_EMAIL": "\n",
            "GITHUB_APP_NAME": None,
            "GITHUB_APP_SLUG": None,
            "GITHUB_APP_ID": None,
            "GITHUB_APP_INSTALLATION_ID": None,
        },
    )

    assert config.GIT_AUTHOR_NAME == config.DEFAULT_GIT_IDENTITY["author_name"]
    assert config.GIT_AUTHOR_EMAIL == config.DEFAULT_GIT_IDENTITY["author_email"]
    assert config.GIT_IDENTITY_SOURCES["author_name"] == "default_placeholder"
    assert config.GIT_IDENTITY_SOURCES["author_email"] == "default_placeholder"
    assert config.GIT_IDENTITY_SOURCES["committer_name"] == "author_fallback"
    assert config.GIT_IDENTITY_SOURCES["committer_email"] == "author_fallback"


def test_app_identity_strips_whitespace(monkeypatch):
    config = _reload_config(
        monkeypatch,
        {
            "GITHUB_APP_NAME": "  My App  ",
            "GITHUB_APP_SLUG": "  my-app  ",
            "GITHUB_APP_ID": "  1234 ",
            "GITHUB_APP_INSTALLATION_ID": None,
            "ADAPTIV_MCP_GIT_AUTHOR_NAME": None,
            "ADAPTIV_MCP_GIT_AUTHOR_EMAIL": None,
            "ADAPTIV_MCP_GIT_COMMITTER_NAME": None,
            "ADAPTIV_MCP_GIT_COMMITTER_EMAIL": None,
        },
    )

    assert config.GIT_AUTHOR_NAME == "My App"
    assert config.GIT_AUTHOR_EMAIL == "my-app[bot]@users.noreply.github.com"
    assert config.GIT_IDENTITY_SOURCES["author_name"] == "app_metadata"
    assert config.GIT_IDENTITY_SOURCES["author_email"] == "app_metadata"

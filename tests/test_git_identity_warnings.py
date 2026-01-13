from __future__ import annotations

import importlib


def _reload_config(monkeypatch, env: dict[str, str | None]):
    # Ensure a clean import each time so module-level identity resolution reruns.
    import github_mcp.config as config

    for key in list(env.keys()):
        if env[key] is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, env[key] or "")

    return importlib.reload(config)


def test_git_identity_warnings_when_placeholders_active(monkeypatch):
    config = _reload_config(
        monkeypatch,
        {
            "GITHUB_MCP_GIT_AUTHOR_NAME": None,
            "GITHUB_MCP_GIT_AUTHOR_EMAIL": None,
            "GITHUB_MCP_GIT_COMMITTER_NAME": None,
            "GITHUB_MCP_GIT_COMMITTER_EMAIL": None,
            "GITHUB_APP_NAME": None,
            "GITHUB_APP_SLUG": None,
            "GITHUB_APP_ID": None,
            "GITHUB_APP_INSTALLATION_ID": None,
        },
    )

    warnings = config.git_identity_warnings()
    # The repo defaults to a stable, non-placeholder identity so deployments can run
    # without requiring explicit git identity env vars.
    assert warnings == []


def test_git_identity_warnings_disabled_when_explicit_configured(monkeypatch):
    config = _reload_config(
        monkeypatch,
        {
            "GITHUB_MCP_GIT_AUTHOR_NAME": "Octo Bot",
            "GITHUB_MCP_GIT_AUTHOR_EMAIL": "octo-bot[bot]@users.noreply.github.com",
            "GITHUB_MCP_GIT_COMMITTER_NAME": "Octo Bot",
            "GITHUB_MCP_GIT_COMMITTER_EMAIL": "octo-bot[bot]@users.noreply.github.com",
            "GITHUB_APP_NAME": None,
            "GITHUB_APP_SLUG": None,
            "GITHUB_APP_ID": None,
            "GITHUB_APP_INSTALLATION_ID": None,
        },
    )

    assert config.git_identity_warnings() == []

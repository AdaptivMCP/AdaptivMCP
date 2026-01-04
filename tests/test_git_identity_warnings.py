import asyncio
import importlib


def _reload_modules(monkeypatch, env_updates):
    for key in (
        "GITHUB_MCP_GIT_AUTHOR_NAME",
        "GITHUB_MCP_GIT_AUTHOR_EMAIL",
        "GITHUB_MCP_GIT_COMMITTER_NAME",
        "GITHUB_MCP_GIT_COMMITTER_EMAIL",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GITHUB_APP_NAME",
        "GITHUB_APP_SLUG",
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    for key, value in env_updates.items():
        monkeypatch.setenv(key, value)

    import github_mcp.config as config
    import github_mcp.http_routes.healthz as healthz
    import github_mcp.main_tools.server_config as server_config

    config = importlib.reload(config)
    healthz = importlib.reload(healthz)
    server_config = importlib.reload(server_config)

    return config, healthz, server_config


def test_identity_placeholder_warning_in_healthz_and_config(monkeypatch):
    config, healthz, server_config = _reload_modules(monkeypatch, {})

    warnings = config.git_identity_warnings()
    assert warnings

    payload = healthz._build_health_payload()
    assert warnings[0] in payload.get("warnings", [])

    config_payload = asyncio.run(server_config.get_server_config())
    assert warnings[0] in config_payload.get("warnings", [])


def test_identity_configured_suppresses_warning(monkeypatch):
    config, healthz, server_config = _reload_modules(
        monkeypatch,
        {
            "GITHUB_MCP_GIT_AUTHOR_NAME": "Octo Bot",
            "GITHUB_MCP_GIT_AUTHOR_EMAIL": "octo-bot[bot]@users.noreply.github.com",
            "GITHUB_MCP_GIT_COMMITTER_NAME": "Octo Bot",
            "GITHUB_MCP_GIT_COMMITTER_EMAIL": "octo-bot[bot]@users.noreply.github.com",
        },
    )

    warnings = config.git_identity_warnings()
    assert not warnings

    payload = healthz._build_health_payload()
    assert not any(
        "Git identity is using placeholder values" in warning
        for warning in payload.get("warnings", [])
    )

    config_payload = asyncio.run(server_config.get_server_config())
    assert not any(
        "Git identity is using placeholder values" in warning
        for warning in config_payload.get("warnings", [])
    )

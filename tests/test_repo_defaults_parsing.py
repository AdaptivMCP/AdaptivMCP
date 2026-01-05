import asyncio
import importlib


def _reload_utils(monkeypatch, raw_value):
    if raw_value is None:
        monkeypatch.delenv("GITHUB_REPO_DEFAULTS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_REPO_DEFAULTS", raw_value)

    import github_mcp.utils as utils

    return importlib.reload(utils)


def test_repo_defaults_parses_valid_json(monkeypatch):
    utils = _reload_utils(monkeypatch, '{"octo/repo":{"default_branch":"develop"}}')

    assert utils.REPO_DEFAULTS == {"octo/repo": {"default_branch": "develop"}}
    assert utils.REPO_DEFAULTS_PARSE_ERROR is None


def test_repo_defaults_missing_env(monkeypatch):
    utils = _reload_utils(monkeypatch, None)

    assert utils.REPO_DEFAULTS == {}
    assert utils.REPO_DEFAULTS_PARSE_ERROR is None


def test_repo_defaults_invalid_json_surfaces_warning(monkeypatch):
    utils = _reload_utils(monkeypatch, '{"octo/repo":')

    assert utils.REPO_DEFAULTS == {}
    assert utils.REPO_DEFAULTS_PARSE_ERROR is not None
    assert "GITHUB_REPO_DEFAULTS" in utils.REPO_DEFAULTS_PARSE_ERROR

    import github_mcp.http_routes.healthz as healthz
    import github_mcp.main_tools.server_config as server_config

    healthz = importlib.reload(healthz)
    server_config = importlib.reload(server_config)

    payload = healthz._build_health_payload()
    assert utils.REPO_DEFAULTS_PARSE_ERROR in payload.get("warnings", [])

    config_payload = asyncio.run(server_config.get_server_config())
    assert utils.REPO_DEFAULTS_PARSE_ERROR in config_payload.get("warnings", [])

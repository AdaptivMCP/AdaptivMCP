import importlib
from typing import Any, Dict

import pytest


def _reload_main_with_env(monkeypatch: pytest.MonkeyPatch, env: Dict[str, str]) -> Any:
    """Reload the main module with a controlled environment mapping.

    This helper clears relevant environment variables first so tests can
    reason about which checks should pass or fail.
    """

    # Clear environment variables that influence validation.
    for key in [
        "GITHUB_PAT",
        "GITHUB_TOKEN",
        "GITHUB_MCP_CONTROLLER_REPO",
        "GITHUB_MCP_CONTROLLER_BRANCH",
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ]:
        monkeypatch.delenv(key, raising=False)

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import main as main_module

    return importlib.reload(main_module)


@pytest.mark.asyncio
async def test_validate_environment_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_main_with_env(monkeypatch, {})

    result = await module.validate_environment()

    assert result["status"] == "error"
    check = next(c for c in result["checks"] if c["name"] == "github_token")
    assert check["level"] == "error"
    assert "not set" in check["message"]

    remote = next(c for c in result["checks"] if c["name"] == "controller_remote_checks")
    assert remote["level"] == "warning"
    assert "Skipped controller repo/branch remote validation" in remote["message"]


@pytest.mark.asyncio
async def test_validate_environment_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_main_with_env(
        monkeypatch,
        {
            "GITHUB_PAT": "ghp_exampletoken",
            "GIT_AUTHOR_NAME": "Ally",
            "GIT_AUTHOR_EMAIL": "ally@example.com",
            "GIT_COMMITTER_NAME": "Ally",
            "GIT_COMMITTER_EMAIL": "ally@example.com",
        },
    )

    calls: Dict[str, Any] = {}

    async def fake_github_request(method: str, path: str, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
        calls.setdefault("paths", []).append(path)
        if path.endswith("/branches/" + module.CONTROLLER_DEFAULT_BRANCH):
            return {"status_code": 200, "json": {}}
        if path.startswith("/repos/") and "/branches/" not in path:
            return {"status_code": 200, "json": {}}
        return {"status_code": 200, "json": {}}

    monkeypatch.setattr(module, "_github_request", fake_github_request)

    result = await module.validate_environment()

    assert result["status"] in {"ok", "warning"}
    summary = result["summary"]
    assert summary["error"] == 0

    token_check = next(c for c in result["checks"] if c["name"] == "github_token")
    assert token_check["level"] == "ok"

    repo_remote = next(c for c in result["checks"] if c["name"] == "controller_repo_remote")
    branch_remote = next(c for c in result["checks"] if c["name"] == "controller_branch_remote")

    assert repo_remote["level"] == "ok"
    assert branch_remote["level"] == "ok"

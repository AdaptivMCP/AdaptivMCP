import importlib

from starlette.testclient import TestClient

import main


def _client() -> TestClient:
    # Re-import the module in case other tests mutated module-level state.
    importlib.reload(main)
    return TestClient(main.app)


def test_healthz_reports_ok_when_token_present(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    client = _client()

    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("Cache-Control", "")
    payload = resp.json()

    assert payload["status"] == "ok"
    assert payload["github_token_present"] is True
    assert payload["controller"] == {
        "repo": main.CONTROLLER_REPO,
        "default_branch": main.CONTROLLER_DEFAULT_BRANCH,
    }
    assert payload["uptime_seconds"] >= 0
    assert set(payload["metrics"]["github"]) >= {
        "requests_total",
        "errors_total",
        "rate_limit_events_total",
        "timeouts_total",
    }


def test_healthz_warns_when_token_missing(monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    client = _client()

    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("Cache-Control", "")
    payload = resp.json()

    assert payload["status"] == "warning"
    assert payload["github_token_present"] is False
    assert payload["uptime_seconds"] >= 0

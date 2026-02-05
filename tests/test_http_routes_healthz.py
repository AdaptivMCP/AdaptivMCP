from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from github_mcp.http_routes import healthz
from github_mcp.exceptions import GitHubAuthError


def _build_client() -> TestClient:
    app = Starlette()
    healthz.register_healthz_route(app)
    return TestClient(app)


def test_healthz_oneshot_default_returns_204_after_first_call(monkeypatch) -> None:
    # Ensure deterministic oneshot behavior.
    monkeypatch.delenv("HEALTHZ_ONESHOT", raising=False)
    healthz._healthz_served_once = False

    # Avoid depending on real environment auth.
    monkeypatch.setattr(healthz, "_get_github_token", lambda: "token")

    client = _build_client()

    first = client.get("/healthz")
    assert first.status_code == 200
    payload = first.json()
    assert payload["status"] == "ok"
    assert payload["github_token_present"] is True

    second = client.get("/healthz")
    assert second.status_code == 204
    assert second.text == ""

    # verbose=1 forces the full JSON payload even in oneshot mode.
    third = client.get("/healthz?verbose=1")
    assert third.status_code == 200
    assert third.json()["status"] == "ok"


def test_healthz_oneshot_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HEALTHZ_ONESHOT", "0")
    healthz._healthz_served_once = False
    monkeypatch.setattr(healthz, "_get_github_token", lambda: "token")

    client = _build_client()

    first = client.get("/healthz")
    assert first.status_code == 200

    second = client.get("/healthz")
    assert second.status_code == 200


def test_healthz_token_present_handles_expected_and_unexpected_errors(
    monkeypatch,
) -> None:
    # Exercise both exception branches in _github_token_present.
    monkeypatch.setenv("HEALTHZ_ONESHOT", "0")
    healthz._healthz_served_once = False

    def _raise_auth() -> str:
        raise GitHubAuthError("no token")

    monkeypatch.setattr(healthz, "_get_github_token", _raise_auth)

    client = _build_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["github_token_present"] is False

    def _raise_unexpected() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(healthz, "_get_github_token", _raise_unexpected)

    resp2 = client.get("/healthz")
    assert resp2.status_code == 200
    assert resp2.json()["github_token_present"] is False

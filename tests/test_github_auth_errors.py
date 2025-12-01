import httpx
import pytest

import main


class _FakeClient:
    def __init__(self, status_code: int, message: str, headers: dict | None = None):
        self._status_code = status_code
        self._message = message
        self._headers = headers or {}

    async def request(self, *_, **__):
        return httpx.Response(
            status_code=self._status_code,
            json={"message": self._message},
            headers=self._headers,
            request=httpx.Request("GET", "https://api.github.com/search/code"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_github_request_raises_auth_error(monkeypatch: pytest.MonkeyPatch, status_code: int):
    monkeypatch.setattr(
        main,
        "_github_client_instance",
        lambda: _FakeClient(status_code, "Requires authentication"),
    )

    with pytest.raises(main.GitHubAuthError) as excinfo:
        await main._github_request("GET", "/search/code")

    message = str(excinfo.value)
    assert "authentication failed" in message.lower()
    assert str(status_code) in message


@pytest.mark.asyncio
async def test_github_request_rate_limit_error(monkeypatch: pytest.MonkeyPatch):
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1735689600"}
    monkeypatch.setattr(
        main,
        "_github_client_instance",
        lambda: _FakeClient(403, "API rate limit exceeded for user", headers=headers),
    )

    with pytest.raises(main.GitHubRateLimitError) as excinfo:
        await main._github_request("GET", "/search/code")

    message = str(excinfo.value).lower()
    assert "rate limit" in message
    assert "resets" in message


@pytest.mark.asyncio
async def test_github_request_429_rate_limit(monkeypatch: pytest.MonkeyPatch):
    main._reset_metrics_for_tests()
    headers = {"Retry-After": "60"}
    monkeypatch.setattr(
        main,
        "_github_client_instance",
        lambda: _FakeClient(429, "secondary rate limit", headers=headers),
    )

    with pytest.raises(main.GitHubRateLimitError) as excinfo:
        await main._github_request("GET", "/search/code")

    message = str(excinfo.value).lower()
    assert "rate limit" in message
    assert "retry" in message
    metrics = main._metrics_snapshot()["github"]
    assert metrics.get("rate_limit_events_total") == 1

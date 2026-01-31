from typing import Any, List, Optional

import pytest

from github_mcp import http_clients
from github_mcp.exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError


class DummyResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: Optional[dict[str, str]] = None,
        text: str = "",
        body: Any = None,
        include_is_error: bool = True,
        is_error: Optional[bool] = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.body = body
        if include_is_error:
            # Allow explicitly overriding is_error to exercise branches.
            self.is_error = is_error if is_error is not None else status_code >= 400


class DummyAsyncClient:
    def __init__(self, responses: List[DummyResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> DummyResponse:
        self.calls.append((method, path))
        if not self._responses:
            raise RuntimeError("No more dummy responses")
        return self._responses.pop(0)


def _install_simple_body_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_clients, "_extract_response_body", lambda resp: getattr(resp, "body", None)
    )

    def _build_payload(resp: Any, *, body: Any = None) -> dict[str, Any]:
        return {
            "status_code": getattr(resp, "status_code", None),
            "headers": dict(getattr(resp, "headers", {}) or {}),
            "body": body,
            "text": getattr(resp, "text", ""),
        }

    monkeypatch.setattr(http_clients, "_build_response_payload", _build_payload)


def test_allow_rate_limit_retries_defaults() -> None:
    assert (
        http_clients._allow_rate_limit_retries("GET", "/repos", allow_retries=None)
        is True
    )
    assert (
        http_clients._allow_rate_limit_retries("HEAD", "/repos", allow_retries=None)
        is True
    )

    # GraphQL queries are POST but should be retryable by default.
    assert (
        http_clients._allow_rate_limit_retries("POST", "/graphql", allow_retries=None)
        is True
    )
    assert (
        http_clients._allow_rate_limit_retries("POST", "/graphql/", allow_retries=None)
        is True
    )

    # Non-idempotent by default.
    assert (
        http_clients._allow_rate_limit_retries("POST", "/repos", allow_retries=None)
        is False
    )

    # Explicit override.
    assert (
        http_clients._allow_rate_limit_retries("POST", "/repos", allow_retries=True)
        is True
    )
    assert (
        http_clients._allow_rate_limit_retries("GET", "/repos", allow_retries=False)
        is False
    )


def test_is_rate_limit_response_detection() -> None:
    resp_429 = DummyResponse(429, headers={}, body={"message": "rate limit"})
    assert http_clients._is_rate_limit_response(
        resp=resp_429, message_lower="rate limit", error_flag=True
    )

    resp_remaining_0 = DummyResponse(
        403, headers={"X-RateLimit-Remaining": "0"}, body={"message": "nope"}
    )
    assert http_clients._is_rate_limit_response(
        resp=resp_remaining_0, message_lower="nope", error_flag=True
    )

    resp_marker = DummyResponse(
        403, headers={}, body={"message": "Secondary rate limit"}
    )
    assert http_clients._is_rate_limit_response(
        resp=resp_marker, message_lower="secondary rate limit", error_flag=True
    )

    # Should not treat success responses as rate-limited.
    resp_ok = DummyResponse(200, headers={}, body={"message": "rate limit"})
    assert (
        http_clients._is_rate_limit_response(
            resp=resp_ok, message_lower="rate limit", error_flag=False
        )
        is False
    )


@pytest.mark.anyio
async def test_throttle_search_requests_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure the per-loop weak state doesn't leak across tests.
    http_clients._search_rate_limit_states.clear()

    monkeypatch.setattr(http_clients, "GITHUB_SEARCH_MIN_INTERVAL_SECONDS", 0.5)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(http_clients.asyncio, "sleep", _fake_sleep)

    # Control time progression.
    times = [
        1000.0,  # first now
        1000.0,  # first update
        1000.2,  # second now
        1000.2,  # second update
    ]

    def _fake_time() -> float:
        return times.pop(0)

    monkeypatch.setattr(http_clients.time, "time", _fake_time)

    await http_clients._throttle_search_requests()
    await http_clients._throttle_search_requests()

    assert sleeps == [pytest.approx(0.3)]


@pytest.mark.anyio
async def test_github_request_retries_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_simple_body_helpers(monkeypatch)

    # Keep retries deterministic.
    monkeypatch.setattr(http_clients, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(http_clients, "GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", 10.0)
    monkeypatch.setattr(http_clients, "GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", 0.1)
    monkeypatch.setattr(
        http_clients, "_parse_rate_limit_delay_seconds", lambda resp: 0.25
    )
    monkeypatch.setattr(
        http_clients, "_jitter_sleep_seconds", lambda delay, *, respect_min: delay
    )

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(http_clients.asyncio, "sleep", _fake_sleep)

    rate_limited = DummyResponse(
        429,
        headers={"Retry-After": "1"},
        text="rate-limited",
        body={"message": "rate limit exceeded"},
    )
    ok = DummyResponse(200, headers={}, text="ok", body={"ok": True})

    client = DummyAsyncClient([rate_limited, ok])

    def _factory() -> DummyAsyncClient:
        return client

    result = await http_clients._github_request(
        "GET", "/repos", client_factory=_factory
    )
    assert result["json"] == {"ok": True}
    assert sleeps == [0.25]
    assert client.calls == [("GET", "/repos"), ("GET", "/repos")]


@pytest.mark.anyio
async def test_github_request_rate_limit_disabled_for_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_simple_body_helpers(monkeypatch)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(http_clients.asyncio, "sleep", _fake_sleep)

    rate_limited = DummyResponse(
        429,
        headers={"Retry-After": "1"},
        text="rate-limited",
        body={"message": "rate limit exceeded"},
    )

    client = DummyAsyncClient([rate_limited])

    with pytest.raises(GitHubRateLimitError) as excinfo:
        await http_clients._github_request(
            "POST", "/repos", client_factory=lambda: client
        )

    assert "retries disabled" in str(excinfo.value).lower()
    assert sleeps == []


@pytest.mark.anyio
async def test_github_request_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_simple_body_helpers(monkeypatch)

    unauthorized = DummyResponse(
        401,
        headers={},
        text="unauthorized",
        body={"message": "Bad credentials"},
    )

    client = DummyAsyncClient([unauthorized])

    with pytest.raises(GitHubAuthError) as excinfo:
        await http_clients._github_request(
            "GET", "/repos", client_factory=lambda: client
        )

    assert "401" in str(excinfo.value)


@pytest.mark.anyio
async def test_github_request_error_flag_fallback_when_is_error_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_simple_body_helpers(monkeypatch)

    # Remove is_error attribute so the fallback branch runs.
    server_error = DummyResponse(
        500,
        headers={},
        text="boom",
        body={"message": "internal"},
        include_is_error=False,
    )

    client = DummyAsyncClient([server_error])

    with pytest.raises(GitHubAPIError) as excinfo:
        await http_clients._github_request(
            "GET", "/repos", client_factory=lambda: client
        )

    assert excinfo.value.status_code == 500
    assert excinfo.value.response_payload is not None

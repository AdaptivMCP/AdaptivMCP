from __future__ import annotations

from dataclasses import dataclass
from typing import Any


from github_mcp.http_utils import extract_response_json, parse_rate_limit_delay_seconds


@dataclass
class _FakeResp:
    headers: dict[str, str]
    _json: Any = None
    _json_raises: Exception | None = None

    def json(self) -> Any:  # noqa: D401
        if self._json_raises is not None:
            raise self._json_raises
        return self._json


def test_extract_response_json_success() -> None:
    resp = _FakeResp(headers={}, _json={"ok": True})
    assert extract_response_json(resp) == {"ok": True}


def test_extract_response_json_failure_returns_none() -> None:
    resp = _FakeResp(headers={}, _json_raises=ValueError("no json"))
    assert extract_response_json(resp) is None


def test_extract_response_json_missing_method_returns_none() -> None:
    class NoJson:
        headers: dict[str, str] = {}

    assert extract_response_json(NoJson()) is None


def test_parse_rate_limit_delay_retry_after_takes_precedence() -> None:
    resp = _FakeResp(headers={"Retry-After": "2", "X-RateLimit-Reset": "9999999999"})
    assert (
        parse_rate_limit_delay_seconds(
            resp, reset_header_names=("X-RateLimit-Reset",), now=0.0
        )
        == 2.0
    )


def test_parse_rate_limit_delay_retry_after_http_date() -> None:
    now = 1_700_000_000.0
    resp = _FakeResp(headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("X-RateLimit-Reset",),
            now=now,
        )
        == 0.0
    )


def test_parse_rate_limit_delay_retry_after_invalid_date_returns_none() -> None:
    resp = _FakeResp(headers={"Retry-After": "nope"})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("X-RateLimit-Reset",),
        )
        is None
    )


def test_parse_rate_limit_delay_epoch_seconds() -> None:
    now = 1_700_000_000.0
    resp = _FakeResp(headers={"X-RateLimit-Reset": str(now + 10.0)})
    assert (
        parse_rate_limit_delay_seconds(
            resp, reset_header_names=("X-RateLimit-Reset",), now=now
        )
        == 10.0
    )


def test_parse_rate_limit_delay_epoch_millis() -> None:
    now = 1_700_000_000.0
    raw_millis = int((now + 5.0) * 1000)
    resp = _FakeResp(headers={"Ratelimit-Reset": str(raw_millis)})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("Ratelimit-Reset",),
            allow_epoch_millis=True,
            now=now,
        )
        == 5.0
    )


def test_parse_rate_limit_delay_duration_seconds_when_allowed() -> None:
    resp = _FakeResp(headers={"Ratelimit-Reset": "3"})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("Ratelimit-Reset",),
            allow_duration_seconds=True,
            now=0.0,
        )
        == 3.0
    )


def test_parse_rate_limit_delay_duration_seconds_disallowed_returns_none() -> None:
    resp = _FakeResp(headers={"Ratelimit-Reset": "3"})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("Ratelimit-Reset",),
            allow_duration_seconds=False,
            now=0.0,
        )
        is None
    )


def test_parse_rate_limit_delay_allows_zero_duration() -> None:
    resp = _FakeResp(headers={"Ratelimit-Reset": "0"})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("Ratelimit-Reset",),
            allow_duration_seconds=True,
            now=123.0,
        )
        == 0.0
    )


def test_parse_rate_limit_delay_ignores_empty_reset_header() -> None:
    resp = _FakeResp(headers={"Ratelimit-Reset": "   "})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("Ratelimit-Reset",),
            allow_duration_seconds=True,
            now=0.0,
        )
        is None
    )


def test_parse_rate_limit_delay_headers_case_insensitive() -> None:
    now = 1_700_000_000.0
    resp = _FakeResp(headers={"x-ratelimit-reset": str(now + 12.0)})
    assert (
        parse_rate_limit_delay_seconds(
            resp,
            reset_header_names=("X-RateLimit-Reset",),
            now=now,
        )
        == 12.0
    )

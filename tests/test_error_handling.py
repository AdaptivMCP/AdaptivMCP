from __future__ import annotations

import asyncio
import importlib
import importlib.util
from typing import Any

import pytest

from github_mcp.exceptions import APIError, GitHubAPIError, WriteApprovalRequiredError
from github_mcp.mcp_server import error_handling as eh


def test_httpx_timeout_fallback(monkeypatch: Any) -> None:
    """Cover the fallback TimeoutException shim when httpx isn't available."""

    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    reloaded = importlib.reload(eh)
    assert hasattr(reloaded.httpx, "TimeoutException")
    assert issubclass(reloaded.httpx.TimeoutException, Exception)

    # Restore normal behavior for other tests.
    monkeypatch.setattr(importlib.util, "find_spec", original_find_spec)
    importlib.reload(eh)


def test_env_int_parses_and_falls_back(monkeypatch: Any) -> None:
    monkeypatch.setenv("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", " 123 ")
    assert eh._env_int("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", 4000) == 123

    monkeypatch.setenv("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", "nope")
    assert eh._env_int("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", 4000) == 4000


def test_preview_text_short_and_long() -> None:
    assert eh._preview_text("hi", head=4, tail=4) == ("hi", "")

    long = "a" * 100
    h, t = eh._preview_text(long, head=10, tail=10)
    assert h == "a" * 10
    assert t == "a" * 10


def test_infer_missing_path_from_message() -> None:
    msg = "[Errno 2] No such file or directory: '/tmp/missing.txt'"
    assert eh._infer_missing_path_from_message(msg) == "/tmp/missing.txt"

    msg2 = "path not found: foo/bar.txt"
    assert eh._infer_missing_path_from_message(msg2) == "foo/bar.txt"

    assert eh._infer_missing_path_from_message("no such file") is None


def test_sanitize_debug_value_redaction_and_truncation(monkeypatch: Any) -> None:
    secret = "A" * 60

    out = eh._sanitize_debug_value({"token": secret})
    assert isinstance(out, dict)
    assert "REDACTED_VALUE" in out["token"]

    # High entropy strings should *not* be redacted under non-secret keys.
    out2 = eh._sanitize_debug_value({"note": secret})
    assert out2["note"] == secret

    assert eh._sanitize_debug_value("Bearer abc") == "<REDACTED_TOKEN>"

    # Force truncation.
    monkeypatch.setenv("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", "200")
    importlib.reload(eh)
    try:
        long = "x" * 500
        truncated = eh._sanitize_debug_value(long)
        assert truncated.startswith("<TRUNCATED_TEXT")
        assert "len=500" in truncated
    finally:
        monkeypatch.delenv("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", raising=False)
        importlib.reload(eh)


def test_sanitize_debug_value_depth_limit_prevents_secret_leak() -> None:
    secret = "A" * 60
    nested = {"token": {"inner": {"token": secret}}}

    out = eh._sanitize_debug_value(nested, max_depth=1)
    assert out["token"] == "<MAX_DEPTH_REACHED>"


def test_structured_tool_error_cancelled() -> None:
    payload = eh._structured_tool_error(
        asyncio.CancelledError(),
        context="testing",
        request={"tool": "x"},
        tool_surface="http",
        routing_hint={"route": "tools"},
    )
    assert payload["status"] == "cancelled"
    assert payload["ok"] is False
    assert payload["error"] == "cancelled"
    assert payload["error_detail"]["category"] == "cancelled"


def test_structured_tool_error_file_not_found_details() -> None:
    exc = FileNotFoundError(2, "No such file or directory", "missing.txt")
    payload = eh._structured_tool_error(exc)
    detail = payload["error_detail"]
    assert detail["category"] == "not_found"
    assert detail["code"] == "FILE_NOT_FOUND"
    assert detail["details"]["missing_path"] == "missing.txt"
    assert detail["details"]["errno"] == 2


def test_structured_tool_error_api_error_mapping_and_retryable() -> None:
    exc = APIError("rate limited", status_code=429, response_payload={"x": 1})
    payload = eh._structured_tool_error(exc)
    detail = payload["error_detail"]
    assert detail["category"] == "rate_limited"
    assert detail.get("retryable") is True
    assert detail["details"]["upstream_status_code"] == 429
    assert detail["details"]["upstream_payload"] == {"x": 1}

    exc2 = APIError("boom", status_code=502)
    payload2 = eh._structured_tool_error(exc2)
    assert payload2["error_detail"]["category"] == "upstream"
    assert payload2["error_detail"].get("retryable") is True

    exc3 = APIError("no status")
    payload3 = eh._structured_tool_error(exc3)
    details3 = payload3["error_detail"].get("details", {})
    assert "upstream_status_code" not in details3


def test_structured_tool_error_github_api_error_patch_inference() -> None:
    exc = GitHubAPIError("Malformed patch: unexpected content")
    payload = eh._structured_tool_error(exc)
    detail = payload["error_detail"]
    assert detail["category"] == "patch"
    assert detail["code"] == "PATCH_MALFORMED"
    assert "upstream_status_code" not in detail.get("details", {})


def test_structured_tool_error_write_approval_required() -> None:
    exc = WriteApprovalRequiredError("needs approval")
    payload = eh._structured_tool_error(exc)
    detail = payload["error_detail"]
    assert detail["category"] == "write_approval_required"
    assert detail["code"] == "WRITE_APPROVAL_REQUIRED"


def test_structured_tool_error_bad_args_keys_fallback() -> None:
    class BadKeysDict(dict[str, Any]):
        def keys(self):  # type: ignore[override]
            raise RuntimeError("boom")

    payload = eh._structured_tool_error(ValueError("bad"), args=BadKeysDict({"x": 1}))
    debug = payload["error_detail"]["debug"]
    assert debug["arg_keys"] == ["<unavailable>"]


def test_structured_tool_error_debug_args_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = eh._structured_tool_error(ValueError("bad"), args={"path": "x"})
    debug = payload["error_detail"]["debug"]
    assert "args" not in debug

    monkeypatch.setenv("ADAPTIV_MCP_ERROR_DEBUG_ARGS", "1")
    payload2 = eh._structured_tool_error(ValueError("bad"), args={"path": "x"})
    debug2 = payload2["error_detail"]["debug"]
    assert debug2["args"]["path"] == "x"


@pytest.mark.parametrize(
    "value",
    [
        {"authorization": "Bearer abc"},
        {"Authorization": "authorization: abc"},
    ],
)
def test_sanitize_debug_value_authorization_header(value: dict[str, str]) -> None:
    out = eh._sanitize_debug_value(value)
    assert out[next(iter(value.keys()))] == "<REDACTED_TOKEN>"

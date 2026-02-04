"""Structured error helpers used across tool and HTTP surfaces.

This module centralizes error normalization so:
- Tool wrappers can return a stable envelope without raising.
- HTTP routes can map errors to status codes reliably.

Contract notes:
- Keep top-level keys stable (status/error/error_detail).
- Add new information under error_detail.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
from typing import Any

if importlib.util.find_spec("httpx") is not None:
    import httpx
else:

    class TimeoutException(Exception):
        """Fallback timeout exception when httpx is unavailable."""

    class _HttpxModule:
        TimeoutException = TimeoutException

    httpx = _HttpxModule()

from github_mcp.exceptions import (
    APIError,
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
    RenderAuthError,
    UsageError,
    WriteApprovalRequiredError,
    WriteNotAuthorizedError,
)

_HIGH_ENTROPY_RE = re.compile(r"^[A-Za-z0-9_\-]{48,}$")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        return int(raw.strip())
    except Exception:
        return int(default)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    raw = raw.strip().lower()
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return bool(default)


_DEBUG_TRUNCATE_CHARS = max(
    200, _env_int("ADAPTIV_MCP_ERROR_DEBUG_TRUNCATE_CHARS", 4000)
)


def _preview_text(text: str, *, head: int = 32, tail: int = 24) -> tuple[str, str]:
    """Return (head, tail) previews for long strings.

    This intentionally preserves a small amount of context while keeping values
    bounded for logs and tool outputs.
    """

    if not isinstance(text, str) or not text:
        return ("", "")
    head = max(0, int(head))
    tail = max(0, int(tail))
    if len(text) <= head + tail:
        return (text, "")
    return (text[:head], text[-tail:] if tail else "")


_SECRET_KEY_RE = re.compile(
    r"(?i)(?:token|secret|api[_-]?key|password|passwd|private[_-]?key|authorization|bearer)"
)


def _sanitize_debug_value(
    value: Any,
    *,
    key: str | None = None,
    max_depth: int = 6,
    _depth: int = 0,
) -> Any:
    """Return a debug-safe version of arbitrary values.

    Validation failures often contain user-provided values. In hosted connector
    environments, returning token-like / high-entropy strings can trigger
    upstream safety blocks. This sanitizer preserves basic shape while
    removing risky payloads.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        s = value
        if not s:
            return s

        lowered = s.strip().lower()
        if lowered.startswith("bearer ") or lowered.startswith("authorization:"):
            return "<REDACTED_TOKEN>"

        key_is_secret = bool(key) and _SECRET_KEY_RE.search(str(key)) is not None

        # Avoid over-redaction: only apply the high-entropy heuristic when the
        # value is clearly associated with a secret-bearing key.
        if key_is_secret and len(s) >= 48 and _HIGH_ENTROPY_RE.match(s):
            h, t = _preview_text(s)
            h = h.replace("\r", " ").replace("\n", " ").replace("\t", " ")
            t = t.replace("\r", " ").replace("\n", " ").replace("\t", " ")
            return f"<REDACTED_VALUE len={len(s)} head={h!r} tail={t!r}>"

        # Avoid emitting very long strings (diffs, blobs, etc.) while keeping
        # enough context for debugging.
        if len(s) > _DEBUG_TRUNCATE_CHARS:
            h, t = _preview_text(s, head=256, tail=256)
            return f"<TRUNCATED_TEXT len={len(s)} head={h!r} tail={t!r}>"

        return s

    if isinstance(value, (bytes, bytearray)):
        return "<BYTES>"

    # Depth limiting is only relevant for containers. Never return raw nested
    # containers once we exceed the maximum depth, as they may contain
    # high-entropy secrets that would otherwise bypass sanitization.
    if _depth >= max_depth and isinstance(value, (dict, list, tuple)):
        return "<MAX_DEPTH_REACHED>"

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            try:
                key = k if isinstance(k, str) else str(k)
            except Exception:
                key = "<unprintable_key>"
            out[key] = _sanitize_debug_value(
                v,
                key=key,
                max_depth=max_depth,
                _depth=_depth + 1,
            )
        return out

    if isinstance(value, (list, tuple)):
        seq = [
            _sanitize_debug_value(v, key=key, max_depth=max_depth, _depth=_depth + 1)
            for v in value
        ]
        return seq if isinstance(value, list) else tuple(seq)

    return value


_MISSING_PATH_RE = re.compile(
    r"(?i)(?:\[errno\s*2\]\s*)?(?:no such file or directory|file not found|path not found)[:\s]+['\"]?(?P<path>[^'\"\n]+)['\"]?"
)


def _infer_missing_path_from_message(message: str) -> str | None:
    """Best-effort extraction of a missing path from a FileNotFound-style message."""

    if not isinstance(message, str) or not message.strip():
        return None

    match = _MISSING_PATH_RE.search(message)
    if not match:
        return None

    path = match.group("path")
    if not isinstance(path, str):
        return None

    path = path.strip()
    if not path or path == ".":
        return None

    # Avoid returning extremely long / surprising values.
    if len(path) > 4096:
        return None

    return path


def _structured_tool_error(
    exc: BaseException,
    *,
    context: str | None = None,
    path: str | None = None,
    tool_descriptor: dict[str, Any] | None = None,
    tool_descriptor_text: str | None = None,
    tool_surface: str | None = None,
    routing_hint: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = str(exc) or exc.__class__.__name__

    # Cancellation is not an error in the conventional sense; it is an execution
    # control signal (user cancel, upstream disconnect, server shutdown). Treat
    # it as a first-class outcome so callers and logs can distinguish it from
    # failures.
    if isinstance(exc, asyncio.CancelledError):
        error_detail: dict[str, Any] = {
            "message": "Tool execution cancelled",
            "category": "cancelled",
            "code": "CANCELLED",
        }
        if context:
            error_detail["context"] = context
        payload: dict[str, Any] = {
            "status": "cancelled",
            "ok": False,
            "error": "cancelled",
            "error_detail": error_detail,
        }
        if request is not None:
            payload["request"] = request
        if tool_surface is not None:
            payload["tool_surface"] = tool_surface
        if routing_hint is not None:
            payload["routing_hint"] = routing_hint
        return payload

    # Best-effort categorization for consistent HTTP status mapping.
    category = "internal"
    code: str | None = None
    details: dict[str, Any] = {}
    retryable = False
    hint: str | None = None
    origin: str | None = None

    # 1) Capture any structured attributes attached to the exception.
    # Tools may raise plain Exceptions, so treat this as opportunistic.
    val = getattr(exc, "code", None)
    if isinstance(val, str) and val.strip():
        code = val.strip()

    val = getattr(exc, "category", None)
    if isinstance(val, str) and val.strip():
        category = val.strip()

    val = getattr(exc, "hint", None)
    if isinstance(val, str) and val.strip():
        hint = val.strip()

    val = getattr(exc, "origin", None)
    if isinstance(val, str) and val.strip():
        origin = val.strip()

    val = getattr(exc, "retryable", None)
    if isinstance(val, bool):
        retryable = val
    elif val is not None:
        retryable = bool(val)

    val = getattr(exc, "details", None)
    if isinstance(val, dict) and val:
        details.update(val)

    # 2) Provider/permission categories.
    if isinstance(exc, FileNotFoundError):
        category = "not_found"
        code = code or "FILE_NOT_FOUND"
        missing_path = (
            path
            or getattr(exc, "filename", None)
            or _infer_missing_path_from_message(message)
        )
        if isinstance(missing_path, str) and missing_path.strip():
            details.setdefault("missing_path", missing_path.strip())
        errno = getattr(exc, "errno", None)
        if errno is not None:
            details.setdefault("errno", errno)
        hint = hint or (
            "File/path not found. Verify the path and ref (branch/commit), or "
            "list/search available paths and retry."
        )

    elif isinstance(exc, (GitHubAuthError, RenderAuthError)):
        category = "auth"
    elif isinstance(exc, GitHubRateLimitError):
        category = "rate_limited"
        code = code or "github_rate_limited"
        retryable = True
    elif isinstance(exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        category = "timeout"
        code = code or "timeout"
        retryable = True
    elif isinstance(exc, (WriteApprovalRequiredError, WriteNotAuthorizedError)):
        category = "permission"
        if isinstance(exc, WriteApprovalRequiredError):
            category = "write_approval_required"
            code = code or "WRITE_APPROVAL_REQUIRED"
    elif isinstance(exc, (ValueError, TypeError)):
        category = "validation"

    # 3) APIError carries upstream status/payload; map common statuses.
    if isinstance(exc, APIError):
        if exc.status_code is not None:
            details.setdefault("upstream_status_code", exc.status_code)
        if isinstance(exc.response_payload, dict) and exc.response_payload:
            details.setdefault("upstream_payload", exc.response_payload)

        if exc.status_code in (400, 422):
            category = "validation"
        if exc.status_code == 401:
            category = "auth"
        elif exc.status_code == 403:
            category = "permission"
        elif exc.status_code == 404:
            category = "not_found"
        elif exc.status_code == 409:
            category = "conflict"
        elif exc.status_code == 429:
            category = "rate_limited"
            retryable = True
        elif isinstance(exc.status_code, int) and exc.status_code >= 500:
            category = "upstream"
            retryable = True

    # 3b) GitHubAPIError is frequently used for local workspace operations and
    # patch application failures. Those errors are not necessarily "internal";
    # infer categories from common message patterns when the exception did not
    # carry an explicit category.
    if isinstance(exc, GitHubAPIError) and category == "internal":
        lowered = (message or "").lower()

        # Patch/diff parsing & formatting errors.
        if (
            "malformed patch" in lowered
            or "patch missing" in lowered
            or "unexpected patch content" in lowered
            or "invalid" in lowered
            and "patch" in lowered
            or "received empty patch" in lowered
            or "unsupported patch action" in lowered
        ):
            category = "patch"
            code = code or "PATCH_MALFORMED"

        # Path validation errors.
        elif lowered.startswith("path must") or "path must" in lowered:
            category = "validation"
            code = code or "PATH_INVALID"

        # Missing files referenced by patches.
        elif (
            "file does not exist" in lowered
            or "no such file" in lowered
            or "path not found" in lowered
            or ("not found" in lowered and "path" in lowered)
        ):
            category = "patch"
            code = code or "FILE_NOT_FOUND"

        # Patch hunks not applying cleanly.
        elif "does not apply" in lowered or "patch does not apply" in lowered:
            category = "patch"
            code = code or "PATCH_DOES_NOT_APPLY"

    # 4) UsageError is a user-facing error by default.
    if isinstance(exc, UsageError) and category == "internal":
        category = "validation"

    error_detail: dict[str, Any] = {
        "message": message,
        "category": category,
    }
    if code:
        error_detail["code"] = code
    if details:
        error_detail["details"] = details
    if retryable:
        error_detail["retryable"] = True
    if hint:
        error_detail["hint"] = hint
    if origin:
        error_detail["origin"] = origin

    # Keep trace/debug nested under error_detail for stable downstream consumers.
    if trace is not None:
        error_detail["trace"] = trace

    # Validation errors frequently include the *original* values (sometimes
    # including tokens or other high-entropy strings). To avoid upstream safety
    # blocks in hosted connector environments, sanitize these argument values.
    if args is not None:
        try:
            debug: dict[str, Any] = {
                "arg_keys": sorted(str(k) for k in args.keys()),
            }
            if _env_flag("ADAPTIV_MCP_ERROR_DEBUG_ARGS", default=False):
                debug["args"] = _sanitize_debug_value(args)
            error_detail["debug"] = debug
        except Exception:
            debug: dict[str, Any] = {"arg_keys": ["<unavailable>"]}
            if _env_flag("ADAPTIV_MCP_ERROR_DEBUG_ARGS", default=False):
                debug["args"] = {}
            error_detail["debug"] = debug

    payload: dict[str, Any] = {
        "status": "error",
        "ok": False,
        "error": message,
        "error_detail": error_detail,
    }
    if context:
        payload["context"] = context
    if path:
        payload["path"] = path
    if request is not None:
        payload["request"] = request
    if tool_surface is not None:
        payload["tool_surface"] = tool_surface
    if routing_hint is not None:
        payload["routing_hint"] = routing_hint
    if tool_descriptor is not None:
        payload["tool_descriptor"] = tool_descriptor
    if tool_descriptor_text is not None:
        payload["tool_descriptor_text"] = tool_descriptor_text

    return payload

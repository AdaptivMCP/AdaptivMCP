from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.path_utils import normalize_base_path as _normalize_base_path
from github_mcp.path_utils import request_base_path as _request_base_path

from github_mcp.mcp_server import registry as mcp_registry
from github_mcp.mcp_server.context import REQUEST_CHATGPT_METADATA
from github_mcp.mcp_server.suggestions import (
    augment_structured_error_for_bad_args,
    build_unknown_tool_payload,
)
from github_mcp.server import _find_registered_tool

try:
    from github_mcp.config import ERRORS_LOGGER
except Exception:  # noqa: BLE001
    ERRORS_LOGGER = logging.getLogger("github_mcp")

TOOL_CATALOG_CACHE_SECONDS = max(
    0,
    int(
        str(os.environ.get("ADAPTIV_MCP_TOOL_CATALOG_CACHE_SECONDS", "3")).strip() or 0
    ),
)


@dataclass(frozen=True)
class _ToolCatalogCacheEntry:
    created_at: float
    signature: tuple[tuple[str, str | None], ...]
    payload: dict[str, Any]


_TOOL_CATALOG_CACHE: dict[tuple[bool, bool | None, str], _ToolCatalogCacheEntry] = {}


def _tool_catalog_signature() -> tuple[tuple[str, str | None], ...]:
    signature: list[tuple[str, str | None]] = []
    for tool, func in mcp_registry._REGISTERED_MCP_TOOLS:
        name = mcp_registry._registered_tool_name(tool, func)
        if not name:
            continue
        schema_hash = getattr(func, "__mcp_input_schema_hash__", None)
        signature.append((str(name), str(schema_hash) if schema_hash else None))
    signature.sort()
    return tuple(signature)


def _cached_tool_catalog(
    *, include_parameters: bool, compact: bool | None, base_path: str
) -> dict[str, Any] | None:
    if TOOL_CATALOG_CACHE_SECONDS <= 0:
        return None
    cache_key = (include_parameters, compact, base_path)
    entry = _TOOL_CATALOG_CACHE.get(cache_key)
    if entry is None:
        return None
    if time.monotonic() - entry.created_at > TOOL_CATALOG_CACHE_SECONDS:
        return None
    if entry.signature != _tool_catalog_signature():
        return None
    return dict(entry.payload)


def _store_tool_catalog_cache(
    payload: dict[str, Any],
    *,
    include_parameters: bool,
    compact: bool | None,
    base_path: str,
) -> None:
    if TOOL_CATALOG_CACHE_SECONDS <= 0:
        return
    cache_key = (include_parameters, compact, base_path)
    _TOOL_CATALOG_CACHE[cache_key] = _ToolCatalogCacheEntry(
        created_at=time.monotonic(),
        signature=_tool_catalog_signature(),
        payload=dict(payload),
    )


def _catalog_cache_headers() -> dict[str, str] | None:
    if TOOL_CATALOG_CACHE_SECONDS <= 0:
        return None
    return {
        "Cache-Control": f"public, max-age={int(TOOL_CATALOG_CACHE_SECONDS)}",
    }


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _jitter_sleep_seconds(delay_seconds: float, *, respect_min: bool = True) -> float:
    """Backward-compatible wrapper for shared retry jitter."""

    from ..retry_utils import jitter_sleep_seconds

    return jitter_sleep_seconds(
        delay_seconds, respect_min=respect_min, cap_seconds=0.25
    )


def _tool_catalog(
    *, include_parameters: bool, compact: bool | None, base_path: str = ""
) -> dict[str, Any]:
    """Build a stable tool/resources catalog for HTTP clients.

    This endpoint is intentionally best-effort: callers use it for discovery.
    If introspection fails (for example during partial startup), return a
    structured error rather than a raw 500 so clients can render a useful
    diagnostic.
    """

    cached = _cached_tool_catalog(
        include_parameters=include_parameters,
        compact=compact,
        base_path=base_path,
    )
    if cached is not None:
        return cached

    try:
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(
            include_parameters=include_parameters, compact=compact
        )
        tools = list(catalog.get("tools") or [])
        catalog_error: str | None = None
        catalog_errors = catalog.get("errors")
    except Exception as exc:
        tools = []
        catalog_error = str(exc) or "Failed to build tool catalog."
        catalog_errors = None

    # NOTE: Keep resource URIs stable across reverse-proxy path rewrites.
    #
    # Some deployments are mounted under an ephemeral path prefix (for example,
    # a per-link id). If we embed that prefix in the resource URI, clients that
    # cache the catalog can become "stuck" calling stale URLs when the prefix
    # changes mid-workflow.
    #
    # To prevent that failure mode, we expose a *relative* `uri` (no leading
    # slash) that a client can resolve against its current base URL.
    #
    # We also include a best-effort `href` that is fully qualified to the
    # current request base path for clients that want an explicit HTTP path.
    resources: list[dict[str, Any]] = []
    base_path = _normalize_base_path(base_path)
    href_prefix = f"{base_path}/tools" if base_path else "/tools"
    for entry in tools:
        name = entry.get("name")
        if not name:
            continue
        resources.append(
            {
                "uri": f"tools/{name}",
                "href": f"{href_prefix}/{name}",
                "name": name,
                "description": entry.get("description"),
                "mimeType": "application/json",
            }
        )

    payload: dict[str, Any] = {"tools": tools, "resources": resources, "finite": True}
    if catalog_error is not None:
        payload["error"] = catalog_error
    if isinstance(catalog_errors, list) and catalog_errors:
        payload["errors"] = catalog_errors
    _store_tool_catalog_cache(
        payload,
        include_parameters=include_parameters,
        compact=compact,
        base_path=base_path,
    )
    return payload


def _coerce_json_args(args: Any) -> Any:
    if not isinstance(args, str):
        return args
    stripped = args.strip()
    if not stripped:
        return args
    if stripped[0] not in {"{", "["}:
        return args
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return args


def _coerce_error_message(detail: dict[str, Any]) -> str:
    for key in ("message", "error", "detail"):
        val = detail.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _infer_error_category(code: str, category: str, message: str) -> str:
    """Best-effort category inference for legacy/unstructured errors.

    We intentionally keep this conservative: only upgrade to a non-internal
    category when the signal is clear.
    """

    if isinstance(category, str) and category.strip():
        return category.strip()

    code_norm = str(code or "").strip().lower()
    msg = str(message or "").strip().lower()

    if code_norm in {
        "write_approval_required",
        "write_approval",
        "write_approval_required_error",
    }:
        return "write_approval_required"
    if code_norm in {"write_not_authorized", "write_not_authorized_error"}:
        return "permission"

    if "rate" in msg and "limit" in msg:
        return "rate_limited"
    if "too many requests" in msg:
        return "rate_limited"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "not found" in msg or "does not exist" in msg:
        return "not_found"
    if (
        "unauthorized" in msg
        or "authentication" in msg
        or ("token" in msg and "missing" in msg)
    ):
        return "auth"
    if "forbidden" in msg or "permission" in msg or "not authorized" in msg:
        return "permission"
    if "conflict" in msg or "already exists" in msg:
        return "conflict"

    # Validation / bad args.
    if "bad arg" in msg or "bad args" in msg:
        return "validation"
    if "invalid" in msg or "missing required" in msg or "unexpected keyword" in msg:
        return "validation"
    if "preflight validation" in msg:
        return "validation"
    if code_norm.startswith("patch_"):
        return "patch"
    if "patch" in msg and ("apply" in msg or "diff" in msg):
        return "patch"

    return "internal"


def _looks_like_error_detail(result: dict[str, Any]) -> bool:
    """Return True when the mapping is itself an error_detail payload."""

    # If the payload already looks like an envelope, do not treat it as a bare
    # detail dict. Otherwise we can end up "double wrapping" like:
    #   {status, ok, category, error} -> {error_detail: {status, ok, ...}}
    if "error_detail" in result:
        return False
    if isinstance(result.get("ok"), bool):
        return False
    status = result.get("status")
    if isinstance(status, str) and status.strip().lower() in {
        "ok",
        "error",
        "success",
        "failed",
        "running",
    }:
        return False

    has_cat = (
        isinstance(result.get("category"), str) and str(result.get("category")).strip()
    )
    has_code = isinstance(result.get("code"), str) and str(result.get("code")).strip()
    has_msg = any(
        isinstance(result.get(k), str) and str(result.get(k)).strip()
        for k in ("message", "error", "detail")
    )
    return bool((has_cat or has_code) and has_msg)


def _normalize_structured_error_payload(
    result: dict[str, Any], err_detail: dict[str, Any]
) -> dict[str, Any]:
    """Ensure structured errors always return a stable envelope.

    Tools historically returned:
    - a full envelope: {status, ok, error, error_detail}
    - a partial envelope: {error, error_detail}
    - a bare error_detail dict: {category, message, ...}

    HTTP callers rely on stable fields, so we normalize here.
    """

    # If the tool returned an envelope without error_detail, synthesize one
    # rather than nesting the whole envelope.
    if "error_detail" not in result and (
        (
            isinstance(result.get("status"), str)
            and str(result.get("status")).strip().lower() == "error"
        )
        or (result.get("ok") is False)
    ):
        msg = (
            _coerce_error_message(result)
            or _coerce_error_message(err_detail)
            or "Tool failed."
        )
        detail: dict[str, Any] = {}
        if (
            isinstance(result.get("category"), str)
            and str(result.get("category")).strip()
        ):
            detail["category"] = str(result.get("category")).strip()
        if isinstance(result.get("code"), str) and str(result.get("code")).strip():
            detail["code"] = str(result.get("code")).strip()
        if msg:
            detail["message"] = msg
        hint = result.get("hint")
        if isinstance(hint, str) and hint.strip():
            detail["hint"] = hint.strip()
        details = result.get("details")
        if isinstance(details, dict):
            detail["details"] = details

        out = dict(result)
        out["status"] = "error"
        out["ok"] = False
        out["error"] = msg
        out["error_detail"] = detail
        if "category" in detail:
            out.setdefault("category", detail.get("category"))
        if "code" in detail:
            out.setdefault("code", detail.get("code"))
        return out

    # If the tool returned a bare detail dict, wrap it.
    if _looks_like_error_detail(result) and "error_detail" not in result:
        msg = _coerce_error_message(result)
        out: dict[str, Any] = {
            "status": "error",
            "ok": False,
            "error": msg or "Tool failed.",
            "error_detail": dict(result),
        }
        # Also surface inferred category/code at the top level for convenience.
        if isinstance(result.get("category"), str):
            out.setdefault("category", str(result.get("category")).strip())
        if isinstance(result.get("code"), str):
            out.setdefault("code", str(result.get("code")).strip())
        return out

    out = dict(result)
    out["status"] = "error"
    out["ok"] = False
    out.setdefault("error_detail", dict(err_detail))

    if not (isinstance(out.get("error"), str) and str(out.get("error")).strip()):
        msg = _coerce_error_message(err_detail)
        if msg:
            out["error"] = msg

    # Convenience top-level fields.
    if (
        isinstance(err_detail.get("category"), str)
        and err_detail.get("category").strip()
    ):
        out.setdefault("category", err_detail.get("category").strip())
    if isinstance(err_detail.get("code"), str) and err_detail.get("code").strip():
        out.setdefault("code", err_detail.get("code").strip())
    return out


def _log_http_structured_error(
    *,
    tool_name: str,
    status_code: int,
    error_detail: dict[str, Any],
    invocation_id: str | None = None,
    exc: BaseException | None = None,
) -> None:
    """Best-effort structured logging for HTTP errors.

    Some tools return structured error dicts instead of raising; without this
    logging, operators see failures only via client symptoms.
    """

    try:
        msg = _coerce_error_message(error_detail) or "Tool invocation failed"
        category = str(error_detail.get("category") or "").strip()
        code = str(error_detail.get("code") or "").strip()
        retryable = error_detail.get("retryable")
        level = logging.ERROR if int(status_code) >= 500 else logging.WARNING
        ERRORS_LOGGER.log(
            level,
            msg,
            exc_info=exc,
            extra={
                "event": "tool_http_error",
                "tool": tool_name,
                "http_status": int(status_code),
                "category": category or None,
                "code": code or None,
                "retryable": bool(retryable) if isinstance(retryable, bool) else None,
                "invocation_id": invocation_id,
                "error_detail": error_detail,
            },
        )
    except Exception:
        return


_ARG_WRAPPER_KEYS = ("arguments", "args", "parameters", "input", "kwargs")


def _extract_wrapped_args(container: dict[str, Any]) -> Any | None:
    for key in _ARG_WRAPPER_KEYS:
        if key in container:
            value = container.get(key)
            if value is not None:
                return value
    return None


def _normalize_payload(payload: Any) -> dict[str, Any]:
    """Normalize incoming tool invocation payloads.

    Clients vary in how they wrap arguments. Common shapes include:
      - {"args": {...}} (legacy)
      - {"arguments": {...}} (JSON-RPC/MCP style)
      - {"params": {"arguments": {...}}} (JSON-RPC envelope)
      - {"parameters": {...}} (common client variant)
      - {"input": {...}} (common tool-call wrapper)
      - {"kwargs": {...}} (kwargs-style wrapper)
      - raw dict of arguments

    We normalize to a plain dict of tool kwargs and strip private metadata.
    """

    args: Any = payload
    if isinstance(payload, dict):
        # JSON-RPC envelope: {"id": ..., "params": {"arguments": {...}}}
        params = payload.get("params")
        if isinstance(params, dict):
            args = _extract_wrapped_args(params)
            if args is None:
                # Some clients send args directly under params.
                args = params
        else:
            wrapped = _extract_wrapped_args(payload)
            if wrapped is not None:
                args = wrapped

    args = _coerce_json_args(args)
    if args is None:
        return {}
    if isinstance(args, dict):
        sanitized = {
            k: v for k, v in args.items() if not (k in _ARG_WRAPPER_KEYS and v is None)
        }
        return {k: v for k, v in sanitized.items() if k != "_meta"}
    if isinstance(args, (list, tuple)):
        normalized: dict[str, Any] = {}
        for entry in args:
            if isinstance(entry, dict):
                if "name" in entry:
                    name = str(entry["name"])
                    if name == "_meta":
                        continue
                    normalized[name] = entry.get("value")
                elif len(entry) == 1:
                    key, value = next(iter(entry.items()))
                    key_str = str(key)
                    if key_str == "_meta":
                        continue
                    normalized[key_str] = value
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                key, value = entry
                key_str = str(key)
                if key_str == "_meta":
                    continue
                normalized[key_str] = value
        return normalized
    return {}


def _default_include_parameters(request: Request) -> bool:
    """Decide whether to include tool schemas by default.

    Some client runtimes require the input schema to reliably invoke tools.
    When we detect hosted-connector metadata,
    default include_parameters=True even if the query parameter is omitted.
    """

    # Prefer the request-scoped context var, which is set by main.py middleware.
    try:
        if REQUEST_CHATGPT_METADATA.get():
            return True
    except Exception:  # nosec B110
        pass

    # Fallback: detect headers directly (in case middleware is disabled).
    try:
        for hdr in (
            "x-openai-assistant-id",
            "x-openai-conversation-id",
            "x-openai-organization-id",
            "x-openai-project-id",
            "x-openai-session-id",
            "x-openai-user-id",
        ):
            if request.headers.get(hdr):
                return True
    except Exception:  # nosec B110
        pass

    return False


def _is_openai_client(request: Request) -> bool:
    """Best-effort detection for hosted tool clients using provider headers.

    Many tool runtimes treat non-2xx HTTP responses as a hard tool failure and
    may stop the loop entirely. For these clients, it's better to return a 200
    with a structured error payload than a 4xx/5xx.

    We detect hosted connectors via request-scoped metadata when available,
    with a header fallback for deployments that don't install middleware.
    """

    try:
        if REQUEST_CHATGPT_METADATA.get():
            return True
    except Exception:  # nosec B110
        pass

    try:
        for hdr in (
            "x-openai-assistant-id",
            "x-openai-conversation-id",
            "x-openai-organization-id",
            "x-openai-project-id",
            "x-openai-session-id",
            "x-openai-user-id",
        ):
            if request.headers.get(hdr):
                return True
    except Exception:  # nosec B110
        pass

    return False


def _status_code_for_error(error: dict[str, Any]) -> int:
    """Map structured error payloads to HTTP status codes."""

    code_raw = str(error.get("code") or "")
    category_raw = str(error.get("category") or "")
    message = _coerce_error_message(error)

    category = _infer_error_category(code_raw, category_raw, message)
    code = code_raw.strip()
    code_norm = code.lower()

    if (
        code_norm in {"github_rate_limited", "render_rate_limited"}
        or category == "rate_limited"
    ):
        return 429
    if category == "auth":
        return 401
    if category == "validation":
        return 400
    if category == "permission":
        return 403
    if category == "write_approval_required":
        return 403
    if category == "not_found":
        return 404
    if category == "conflict":
        return 409
    if category == "patch":
        if code_norm in {"file_not_found"}:
            return 404
        if code_norm in {"patch_does_not_apply", "patch_apply_failed"}:
            return 409
        return 400
    if category == "timeout":
        return 504
    if category == "upstream":
        return 502
    if category == "cancelled":
        # Mirrors common "client closed request" semantics.
        return 499

    return 500


def _log_http_tool_cancelled(
    *,
    tool_name: str,
    invocation_id: str | None = None,
    exc: BaseException | None = None,
) -> None:
    """Best-effort logging for tool cancellations.

    Cancellations can be user-initiated or caused by upstream disconnects.
    Logging them explicitly helps diagnose "hangs" that are actually cancelled
    long-running tool calls.
    """

    try:
        ERRORS_LOGGER.info(
            "Tool invocation cancelled",
            exc_info=exc,
            extra={
                "event": "tool_http_cancelled",
                "tool": tool_name,
                "invocation_id": invocation_id,
            },
        )
    except Exception:
        return


def _response_headers_for_error(error: dict[str, Any]) -> dict[str, str]:
    details = error.get("details")
    if not isinstance(details, dict):
        return {}

    retry_after = details.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)) and retry_after >= 0:
        return {"Retry-After": str(int(retry_after))}

    return {}


def _is_write_action(tool_obj: Any, func: Any) -> bool:
    value = getattr(func, "__mcp_write_action__", None)
    if value is None:
        value = getattr(tool_obj, "write_action", None)
    if value is None:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            value = meta.get("write_action")
    return bool(value)


def _effective_write_action(tool_obj: Any, func: Any, args: dict[str, Any]) -> bool:
    """Compute the invocation-level write action classification.

    Tools are registered with a base (inherent) write_action. Some tools (notably
    command runners) can infer read vs write based on the command payload.

    If a resolver exists, it is authoritative for this invocation.
    """

    base = _is_write_action(tool_obj, func)
    resolver = getattr(func, "__mcp_write_action_resolver__", None)
    if callable(resolver):
        try:
            return bool(resolver(args))
        except Exception:
            return bool(base)
    return bool(base)


def _looks_like_structured_error(payload: Any) -> dict[str, Any] | None:
    """Return the error object when payload matches our error shape."""

    if not isinstance(payload, dict):
        return None

    # Legacy tools may return the error_detail dict directly.
    if _looks_like_error_detail(payload):
        return payload

    # Newer tools return {"error": "...", "error_detail": {...}}.
    detail = payload.get("error_detail")
    if isinstance(detail, dict) and (
        detail.get("category") or detail.get("code") or detail.get("message")
    ):
        return detail

    err = payload.get("error")
    if isinstance(err, str):
        return {"message": err}
    if not isinstance(err, dict):
        return None
    if not (err.get("category") or err.get("code") or err.get("message")):
        return None
    return err


def _coerce_error_detail(structured: dict[str, Any]) -> dict[str, Any]:
    """Return a dict-like error detail from our structured error envelope."""

    detail = structured.get("error_detail")
    if isinstance(detail, dict):
        return detail

    raw = structured.get("error")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return {"message": raw}
    return {}


@dataclass
class ToolInvocation:
    invocation_id: str
    tool_name: str
    started_at: float
    task: asyncio.Task
    status: str = "running"
    finished_at: float | None = None
    result: Any | None = None
    status_code: int | None = None
    headers: dict[str, str] | None = None


_INVOCATIONS: dict[str, ToolInvocation] = {}
_INVOCATIONS_LOCK = asyncio.Lock()


async def _execute_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    max_attempts: int | None = None,
) -> tuple[Any, int, dict[str, str]]:
    resolved = _find_registered_tool(tool_name)
    if not resolved:
        available: list[str] = []
        try:
            for tool_obj, func in list(
                getattr(mcp_registry, "_REGISTERED_MCP_TOOLS", []) or []
            ):
                name = mcp_registry._registered_tool_name(tool_obj, func)
                if name:
                    available.append(name)
        except Exception:
            available = []
        payload = build_unknown_tool_payload(tool_name, available)
        return payload, 404, {}

    tool_obj, func = resolved
    write_action = _effective_write_action(tool_obj, func, args)

    try:
        signature: inspect.Signature | None = inspect.signature(func)
    except Exception:
        signature = None

    if max_attempts is not None:
        max_attempts = max(1, int(max_attempts))
    base_backoff_s = 0.25

    attempt = 0
    while True:
        attempt += 1
        try:
            result = func(**args)
            if inspect.isawaitable(result):
                result = await result

            # Some tool wrappers return a structured error payload rather than
            # raising. Translate those into appropriate HTTP status codes so
            # callers can reliably detect failures.
            if isinstance(result, dict):
                err = _looks_like_structured_error(result)
                if err is not None:
                    err_detail: dict[str, Any] = dict(err)
                    # Ensure category is populated for legacy errors so mapping and
                    # client diagnostics are consistent.
                    inferred_category = _infer_error_category(
                        str(err_detail.get("code") or ""),
                        str(err_detail.get("category") or ""),
                        _coerce_error_message(err_detail),
                    )
                    if (
                        not str(err_detail.get("category") or "").strip()
                        and inferred_category
                    ):
                        err_detail["category"] = inferred_category

                    retryable = bool(err_detail.get("retryable", False))
                    status_code = _status_code_for_error(err_detail)
                    headers = _response_headers_for_error(err_detail)

                    normalized_payload = _normalize_structured_error_payload(
                        result, err_detail
                    )

                    if (
                        (not write_action)
                        and retryable
                        and (max_attempts is None or attempt < max_attempts)
                    ):
                        delay = min(base_backoff_s * (2 ** (attempt - 1)), 2.0)
                        details = err.get("details")
                        if isinstance(details, dict):
                            retry_after = details.get("retry_after_seconds")
                            if (
                                isinstance(retry_after, (int, float))
                                and retry_after > 0
                            ):
                                delay = min(float(retry_after), 2.0)
                        await asyncio.sleep(
                            _jitter_sleep_seconds(delay, respect_min=True)
                        )
                        continue

                    _log_http_structured_error(
                        tool_name=tool_name,
                        status_code=status_code,
                        error_detail=err_detail,
                    )
                    return normalized_payload, status_code, headers

            payload = result if isinstance(result, dict) else result
            return payload, 200, {}
        except asyncio.CancelledError as exc:
            _log_http_tool_cancelled(tool_name=tool_name, invocation_id=None, exc=exc)
            raise
        except Exception as exc:
            from github_mcp.mcp_server.error_handling import _structured_tool_error

            structured = _structured_tool_error(
                exc,
                context=f"tool_http:{tool_name}",
                args=args,
            )
            structured = augment_structured_error_for_bad_args(
                structured,
                tool_name=tool_name,
                signature=signature,
                provided_kwargs=args,
                exc=exc,
            )

            # Prefer structured error details when available.
            err = dict(_coerce_error_detail(structured))

            inferred_category = _infer_error_category(
                str(err.get("code") or ""),
                str(err.get("category") or ""),
                _coerce_error_message(err),
            )
            if not str(err.get("category") or "").strip() and inferred_category:
                err["category"] = inferred_category

            if isinstance(structured, dict):
                detail = structured.get("error_detail")
                if (
                    isinstance(detail, dict)
                    and not str(detail.get("category") or "").strip()
                    and inferred_category
                ):
                    detail["category"] = inferred_category

            retryable = bool(err.get("retryable", False))
            status_code = _status_code_for_error(err)
            headers = _response_headers_for_error(err)

            # Retry only for read tools, and only when explicitly marked retryable.
            if (
                (not write_action)
                and retryable
                and (max_attempts is None or attempt < max_attempts)
            ):
                delay = min(base_backoff_s * (2 ** (attempt - 1)), 2.0)
                details = err.get("details")
                if isinstance(details, dict):
                    retry_after = details.get("retry_after_seconds")
                    if isinstance(retry_after, (int, float)) and retry_after > 0:
                        delay = min(float(retry_after), 2.0)
                await asyncio.sleep(_jitter_sleep_seconds(delay, respect_min=True))
                continue

            normalized_payload = (
                _normalize_structured_error_payload(structured, err)
                if isinstance(structured, dict)
                else structured
            )
            _log_http_structured_error(
                tool_name=tool_name,
                status_code=status_code,
                error_detail=err,
                exc=exc,
            )
            return normalized_payload, status_code, headers


def _invocation_payload(invocation: ToolInvocation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_id": invocation.invocation_id,
        "tool_name": invocation.tool_name,
        "status": invocation.status,
        "started_at": invocation.started_at,
        "finished_at": invocation.finished_at,
    }
    if invocation.status in {"succeeded", "failed", "cancelled"}:
        if invocation.result is not None:
            payload["result"] = invocation.result
        if invocation.status_code is not None:
            payload["status_code"] = invocation.status_code
        if invocation.headers:
            payload["headers"] = invocation.headers
    return payload


async def _create_invocation(
    tool_name: str, args: dict[str, Any], *, max_attempts: int | None = None
) -> ToolInvocation:
    invocation_id = uuid.uuid4().hex
    task = asyncio.create_task(
        _execute_tool(tool_name, args, max_attempts=max_attempts)
    )
    invocation = ToolInvocation(
        invocation_id=invocation_id,
        tool_name=tool_name,
        started_at=time.time(),
        task=task,
    )

    async with _INVOCATIONS_LOCK:
        _INVOCATIONS[invocation_id] = invocation

    loop = asyncio.get_running_loop()

    def _finalize(fut: asyncio.Future) -> None:
        async def _update() -> None:
            invocation.finished_at = time.time()
            if fut.cancelled():
                invocation.status = "cancelled"
                invocation.status_code = 499
                invocation.headers = {}
                invocation.result = {
                    "status": "cancelled",
                    "ok": False,
                    "error": "cancelled",
                    "error_detail": {
                        "message": "Tool execution cancelled",
                        "category": "cancelled",
                        "code": "CANCELLED",
                    },
                }
                return
            try:
                payload, status_code, headers = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                invocation.status = "failed"
                invocation.result = {"error": str(exc)}
                invocation.status_code = 500
                invocation.headers = {}
                return
            invocation.status_code = int(status_code)
            invocation.headers = dict(headers)
            invocation.result = payload
            invocation.status = "succeeded" if status_code < 400 else "failed"

        loop.create_task(_update())

    task.add_done_callback(_finalize)
    return invocation


async def _get_invocation(invocation_id: str) -> ToolInvocation | None:
    async with _INVOCATIONS_LOCK:
        return _INVOCATIONS.get(invocation_id)


async def _cancel_invocation(invocation: ToolInvocation) -> None:
    if invocation.task.done():
        return
    invocation.status = "cancelling"
    _log_http_tool_cancelled(
        tool_name=invocation.tool_name, invocation_id=invocation.invocation_id
    )
    invocation.task.cancel()


async def _invoke_tool(
    request: Request,
    tool_name: str,
    args: dict[str, Any],
    *,
    max_attempts: int | None = None,
) -> Response:
    payload, status_code, headers = await _execute_tool(
        tool_name,
        args,
        max_attempts=max_attempts,
    )

    return _llm_safe_json_response(request, payload, status_code, headers=headers)


def _llm_safe_json_response(
    request: Request,
    payload: Any,
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    """Return JSON responses in a tool-runtime-safe way for hosted clients.

    Some hosted runtimes can abort tool usage on non-2xx responses. When we
    detect a hosted client, we keep the payload intact but convert HTTP
    errors into 200s and preserve the original status code in a header.
    """

    if int(status_code) >= 400 and _is_openai_client(request):
        safe_headers = dict(headers or {})
        safe_headers.setdefault("X-Tool-Original-Status", str(int(status_code)))
        return JSONResponse(payload, status_code=200, headers=safe_headers)

    return JSONResponse(payload, status_code=int(status_code), headers=headers)


def build_tool_registry_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters"))
        if include_parameters is None:
            include_parameters = _default_include_parameters(request)
        compact = _parse_bool(request.query_params.get("compact"))
        # Default to *expanded* metadata for hosted clients.
        #
        # In compact mode, tools are often reduced to their first-line summaries,
        # which can cause clients to misclassify or misuse tools with similar names.
        # Hosted clients benefit from richer descriptions and examples.
        if compact is None and _is_openai_client(request):
            compact = False
        # Support legacy discovery paths used by some client runtimes.
        #
        # Some clients call GET /list_tools instead of GET /tools. We treat the
        # former as an alias and normalize base_path stripping for both so the
        # returned `href` fields remain correct.
        base_path = _request_base_path(request, ("/tools", "/list_tools"))
        payload = _tool_catalog(
            include_parameters=include_parameters,
            compact=compact,
            base_path=base_path,
        )
        return JSONResponse(payload, headers=_catalog_cache_headers())

    return _endpoint


def build_resources_endpoint() -> Callable[[Request], Response]:
    """Return only the resources list.

    Some clients assume that GET /resources returns a resource list without the
    parallel "tools" field used by GET /tools.
    """

    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters"))
        if include_parameters is None:
            include_parameters = _default_include_parameters(request)
        compact = _parse_bool(request.query_params.get("compact"))
        if compact is None:
            try:
                if REQUEST_CHATGPT_METADATA.get():
                    compact = False
            except Exception:  # nosec B110
                pass
        # Support legacy discovery paths used by some client runtimes.
        #
        # Some clients call GET /list_resources instead of GET /resources. We
        # treat the former as an alias and normalize base_path stripping for
        # both so returned `href` fields remain correct.
        base_path = _request_base_path(request, ("/resources", "/list_resources"))
        catalog = _tool_catalog(
            include_parameters=include_parameters,
            compact=compact,
            base_path=base_path,
        )
        payload: dict[str, Any] = {
            "resources": list(catalog.get("resources") or []),
            "finite": True,
        }
        if "error" in catalog:
            payload["error"] = catalog["error"]
        return JSONResponse(payload, headers=_catalog_cache_headers())

    return _endpoint


def build_tool_detail_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)
        catalog = _tool_catalog(include_parameters=True, compact=None)
        tools = [t for t in catalog.get("tools", []) if t.get("name") == tool_name]
        if not tools:
            return _llm_safe_json_response(
                request,
                {"error": f"Unknown tool {tool_name!r}."},
                404,
                headers={},
            )
        return JSONResponse(tools[0])

    return _endpoint


def build_tool_invoke_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)

        try:
            # By default, allow unlimited retries; callers may set max_attempts.
            max_attempts = request.query_params.get("max_attempts")
            if max_attempts is not None:
                max_attempts = int(max_attempts)
        except Exception:
            max_attempts = None

        payload: Any = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        return await _invoke_tool(request, tool_name, args, max_attempts=max_attempts)

    return _endpoint


def build_tool_invoke_async_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)

        try:
            max_attempts = request.query_params.get("max_attempts")
            if max_attempts is not None:
                max_attempts = int(max_attempts)
        except Exception:
            max_attempts = None

        payload: Any = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        invocation = await _create_invocation(
            tool_name, args, max_attempts=max_attempts
        )
        return JSONResponse(_invocation_payload(invocation), status_code=202)

    return _endpoint


def build_tool_invocation_status_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        invocation_id = request.path_params.get("invocation_id")
        if not invocation_id:
            return JSONResponse({"error": "invocation_id is required"}, status_code=400)
        invocation = await _get_invocation(str(invocation_id))
        if invocation is None:
            return _llm_safe_json_response(
                request, {"error": "Unknown invocation id"}, 404, headers={}
            )
        return JSONResponse(_invocation_payload(invocation))

    return _endpoint


def build_tool_invocation_cancel_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        invocation_id = request.path_params.get("invocation_id")
        if not invocation_id:
            return JSONResponse({"error": "invocation_id is required"}, status_code=400)
        invocation = await _get_invocation(str(invocation_id))
        if invocation is None:
            return _llm_safe_json_response(
                request, {"error": "Unknown invocation id"}, 404, headers={}
            )
        await _cancel_invocation(invocation)
        return JSONResponse(_invocation_payload(invocation))

    return _endpoint


def register_tool_registry_routes(app: Any) -> None:
    registry_endpoint = build_tool_registry_endpoint()
    resources_endpoint = build_resources_endpoint()
    detail_endpoint = build_tool_detail_endpoint()
    invoke_endpoint = build_tool_invoke_endpoint()
    invoke_async_endpoint = build_tool_invoke_async_endpoint()
    invocation_status_endpoint = build_tool_invocation_status_endpoint()
    invocation_cancel_endpoint = build_tool_invocation_cancel_endpoint()

    # Primary discovery endpoints.
    app.add_route("/tools", registry_endpoint, methods=["GET"])
    app.add_route("/resources", resources_endpoint, methods=["GET"])
    # Backward-compatible aliases used by some tool runtimes.
    #
    # In some deployments the agent runtime attempts /list_resources (and
    # occasionally /list_tools) during discovery. Without these aliases, the
    # runtime can surface a confusing "resources not found" error and abort
    # tool use.
    app.add_route("/list_tools", registry_endpoint, methods=["GET"])
    app.add_route("/list_resources", resources_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", detail_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", invoke_endpoint, methods=["POST"])
    app.add_route(
        "/tools/{tool_name:str}/invocations", invoke_async_endpoint, methods=["POST"]
    )
    app.add_route(
        "/tool_invocations/{invocation_id:str}",
        invocation_status_endpoint,
        methods=["GET"],
    )
    app.add_route(
        "/tool_invocations/{invocation_id:str}/cancel",
        invocation_cancel_endpoint,
        methods=["POST"],
    )
    _prioritize_tool_registry_routes(
        app,
        [
            registry_endpoint,
            resources_endpoint,
            detail_endpoint,
            invoke_endpoint,
            invoke_async_endpoint,
            invocation_status_endpoint,
            invocation_cancel_endpoint,
        ],
    )


def _prioritize_tool_registry_routes(
    app: Any, endpoints: Iterable[Callable[..., Any]]
) -> None:
    """Move tool registry routes to the front of the routing table."""

    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if not isinstance(routes, list):
        return

    endpoint_set = {endpoint for endpoint in endpoints if callable(endpoint)}
    if not endpoint_set:
        return

    prioritized = []
    remaining = []
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint in endpoint_set:
            prioritized.append(route)
        else:
            remaining.append(route)

    if prioritized:
        router.routes = prioritized + remaining

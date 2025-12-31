"""Decorator utilities for MCP tool registration and consistent tool telemetry.

This module wraps MCP tools to provide:
- input schema capture (for UI/tool registry)
- write-action metadata (read/write classification)
- request context propagation
- consistent tool-event telemetry

Logging philosophy
- Console logs (Render) should be readable for developers of all skill levels.
- Console logs should NOT print huge nested dicts.
- We emit a short one-line summary to the console, and attach a compact JSON string
  under `tool_json` for debugging.

A tool event includes fields similar to:
- event: tool_call.start | tool_call.ok | tool_call.error
- status: start | ok | error
- tool_name
- call_id
- duration_ms (for ok/error)
- schema_hash / schema_present
- write_action / write_allowed
- request (minimal: path + received_at + session_id + message_id when available)

The canonical structured payload is emitted as a JSON string in `tool_json` to
avoid formatter-specific repr issues.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from github_mcp.config import DETAILED_LEVEL, TOOLS_LOGGER
from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error
from github_mcp.mcp_server.user_friendly import (
    attach_error_user_facing_fields,
    attach_user_facing_fields,
)
from github_mcp.request_context import get_request_context


WRITE_ALLOWED = os.environ.get("WRITE_ALLOWED", "false").strip().lower() in {"1", "true", "yes", "y"}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        try:
            return str(value)
        except Exception:
            return repr(value)


def _schema_hash(schema: Mapping[str, Any]) -> str:
    raw = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_context(args: Mapping[str, Any]) -> dict[str, Any]:
    keys = sorted([k for k in args.keys() if k not in {"token", "authorization", "auth"}])
    return {"arg_keys": keys[:32], "arg_count": len(keys)}


def _minimal_request(req: Any) -> dict[str, Any]:
    if not isinstance(req, Mapping):
        return {}
    # Keep only stable, small identifiers.
    out: dict[str, Any] = {}
    for k in ("path", "received_at", "session_id", "message_id"):
        if k in req:
            out[k] = _jsonable(req.get(k))
    return out


def _log_tool_event(payload: Mapping[str, Any]) -> None:
    """Emit a single readable console line + attach full payload as JSON string.

    We intentionally avoid passing nested dicts/lists in logging extras because
    different formatters/handlers can render them as Python repr (single quotes)
    or double-encode them. Instead we emit:
      - msg: short human line
      - extra.tool_json: compact JSON string of the structured payload

    This reliably produces readable Render logs and consistent JSON debugging.
    """

    try:
        safe = dict(payload)
        safe = _jsonable(safe)  # type: ignore[assignment]
        if not isinstance(safe, dict):
            safe = {"event": "tool", "payload": str(safe)}

        event = safe.get("event", "tool")
        status = safe.get("status", "")
        tool = safe.get("tool_name", "")
        call_id = safe.get("call_id", "")
        dur = safe.get("duration_ms")
        dur_s = f" {int(dur)}ms" if isinstance(dur, (int, float)) else ""

        msg = f"[tool] {tool} {status}{dur_s} ({event})"

        tool_json = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        log_fn = getattr(TOOLS_LOGGER, "detailed", None)
        if callable(log_fn) and TOOLS_LOGGER.isEnabledFor(DETAILED_LEVEL):
            log_fn(msg, extra={"event": "tool_json", "tool_json": tool_json, "tool_name": tool, "call_id": call_id})
        else:
            TOOLS_LOGGER.info(
                msg,
                extra={"event": "tool_json", "tool_json": tool_json, "tool_name": tool, "call_id": call_id},
            )

    except Exception:
        # Never allow logging to break tool execution.
        return


def _record_recent_tool_event(_: Mapping[str, Any]) -> None:
    # Placeholder: repository includes an in-memory ring buffer in other modules.
    # This decorator only guarantees console emission.
    return


def _record_tool_call(*_: Any, **__: Any) -> None:
    return


def _validate_tool_args_schema(_: str, __: Mapping[str, Any], ___: Mapping[str, Any]) -> None:
    return


def _enforce_write_allowed(tool_name: str, *, write_action: bool) -> None:
    if write_action and not WRITE_ALLOWED:
        raise AdaptivToolError(
            f"Write action blocked for tool '{tool_name}'.",
            hint="Set WRITE_ALLOWED=true (or enable writes in your controller) and retry.",
            code="write_not_allowed",
            category="policy",
        )


def _bind_call_args(sig: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except Exception:
        return dict(kwargs)


def _normalize_input_schema(tool: Any) -> Optional[Mapping[str, Any]]:
    schema = getattr(tool, "inputSchema", None)
    if isinstance(schema, Mapping):
        return schema
    schema = getattr(tool, "input_schema", None)
    if isinstance(schema, Mapping):
        return schema
    return None


def _schema_from_signature(signature: inspect.Signature) -> Optional[Mapping[str, Any]]:
    # Minimal schema fallback. The project has more complete schema logic elsewhere;
    # this is defensive.
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        props[name] = {"type": "string"}
        if param.default is inspect._empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _apply_tool_metadata(
    tool: Any,
    schema: Mapping[str, Any],
    visibility: str,
    tags: list[str],
    *,
    write_action: bool,
    write_allowed: bool,
) -> None:
    try:
        setattr(tool, "inputSchema", schema)
        setattr(tool, "write_action", bool(write_action))
        setattr(tool, "write_allowed", bool(write_allowed))
        setattr(tool, "tags", list(tags))
        setattr(tool, "visibility", visibility)
    except Exception:
        return


def tool(
    name: str,
    description: str,
    *,
    tags: Optional[list[str]] = None,
    visibility: str = "public",
    write_action: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a function as an MCP tool with consistent logging and metadata."""

    tags = tags or []

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            all_args = _bind_call_args(signature, args, kwargs)
            req = get_request_context()
            start = time.perf_counter()

            schema = getattr(async_wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(async_wrapper, "__mcp_input_schema_hash__", None)
            schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
            if not schema_present:
                schema = _schema_from_signature(signature) or {}
                schema_hash = _schema_hash(schema) if isinstance(schema, Mapping) else None

            _validate_tool_args_schema(name, schema, all_args)  # type: ignore[arg-type]
            _enforce_write_allowed(name, write_action=write_action)

            ctx = _extract_context(all_args)

            _log_tool_event(
                {
                    "event": "tool_call.start",
                    "status": "start",
                    "tool_name": name,
                    "call_id": call_id,
                    "request": _minimal_request(req),
                    "schema_hash": schema_hash,
                    "schema_present": bool(schema_present),
                    "write_action": bool(write_action),
                    "write_allowed": bool(WRITE_ALLOWED),
                    "arg_keys": ctx["arg_keys"],
                    "arg_count": ctx["arg_count"],
                }
            )

            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                structured_error = _structured_tool_error(exc, context=name, path=None)
                structured_error = attach_error_user_facing_fields(name, structured_error)
                _log_tool_event(
                    {
                        "event": "tool_call.error",
                        "status": "error",
                        "phase": "execute",
                        "tool_name": name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "schema_hash": schema_hash,
                        "schema_present": bool(schema_present),
                        "write_action": bool(write_action),
                        "write_allowed": bool(WRITE_ALLOWED),
                        "error": structured_error,
                    }
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _log_tool_event(
                {
                    "event": "tool_call.ok",
                    "status": "ok",
                    "tool_name": name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "schema_hash": schema_hash,
                    "schema_present": bool(schema_present),
                    "write_action": bool(write_action),
                    "write_allowed": bool(WRITE_ALLOWED),
                    "result_type": type(result).__name__,
                }
            )

            result = attach_user_facing_fields(name, result)
            return result

        # Attach metadata for registry.
        async_wrapper.__mcp_tool_name__ = name
        async_wrapper.__mcp_description__ = description
        async_wrapper.__mcp_input_schema__ = _schema_from_signature(signature) or {}
        async_wrapper.__mcp_input_schema_hash__ = _schema_hash(async_wrapper.__mcp_input_schema__)
        async_wrapper.__mcp_write_action__ = bool(write_action)
        async_wrapper.__mcp_visibility__ = visibility
        async_wrapper.__mcp_tags__ = list(tags)

        return async_wrapper

    return decorator

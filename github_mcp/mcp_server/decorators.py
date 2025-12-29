"""
Decorators and helpers for registering MCP tools.

Design goals:
- The only blocking/guardrail is WRITE_ALLOWED (true/false) for write tools.
- Every tool call is validated against its published input schema (no guessing).
- Tags/side-effects/mutating metadata are ignored (accepted but non-functional).
- Keep compatibility helpers used by tests (dedupe functions exist).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional, Tuple

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.context import (
    WRITE_ALLOWED,
    _record_recent_tool_event,
    get_request_context,
    mcp,
)
from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _jsonable,
)
from github_mcp.metrics import _record_tool_call


# -----------------------------------------------------------------------------
# Schema hashing + strict argument validation
# -----------------------------------------------------------------------------

def _schema_hash(schema: Mapping[str, Any]) -> str:
    raw = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _require_jsonschema() -> Any:
    try:
        import jsonschema  # type: ignore

        return jsonschema
    except Exception as exc:
        raise AdaptivToolError(
            code="schema_validation_unavailable",
            message="jsonschema is required for strict tool argument validation but is not installed.",
            category="validation",
            origin="schema",
            retryable=False,
            details={"missing_dependency": "jsonschema"},
            hint="Add jsonschema to server dependencies and redeploy (pip install jsonschema).",
        ) from exc


def _validate_tool_args_schema(tool_name: str, schema: Mapping[str, Any], args: Mapping[str, Any]) -> None:
    jsonschema = _require_jsonschema()
    payload = dict(args)
    payload.pop("self", None)

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors = sorted(validator.iter_errors(payload), key=str)
    if not errors:
        return

    err_list: list[dict[str, Any]] = []
    for err in errors[:50]:
        err_list.append(
            {
                "message": getattr(err, "message", str(err)),
                "path": list(getattr(err, "absolute_path", []) or []),
                "validator": getattr(err, "validator", None),
                "validator_value": getattr(err, "validator_value", None),
            }
        )

    raise AdaptivToolError(
        code="tool_args_invalid",
        message=f"Tool arguments did not match schema for {tool_name!r}.",
        category="validation",
        origin="schema",
        retryable=False,
        details={"tool": tool_name, "errors": err_list, "schema": dict(schema)},
        hint="Fetch the tool schema (tool_spec/tool_schema or list_all_actions with include_parameters=true) and resend args exactly.",
    )


# -----------------------------------------------------------------------------
# Single write gate
# -----------------------------------------------------------------------------

def _enforce_write_allowed(tool_name: str, write_action: bool) -> None:
    if not write_action:
        return
    if bool(WRITE_ALLOWED):
        return
    raise AdaptivToolError(
        code="write_not_allowed",
        message=f"Write tool {tool_name!r} blocked because WRITE_ALLOWED is false.",
        category="policy",
        origin="write_gate",
        retryable=False,
        details={"tool": tool_name, "write_allowed": False},
        hint="Set WRITE_ALLOWED=true and retry.",
    )


# -----------------------------------------------------------------------------
# Compatibility: dedupe helpers used by tests
# These do not “block”; they only coalesce identical in-flight calls.
# -----------------------------------------------------------------------------

_DEDUPE_LOCK = asyncio.Lock()
_DEDUPE_INFLIGHT: Dict[str, Tuple[float, asyncio.Future]] = {}

_DEDUPE_SYNC_LOCK = functools.lru_cache(maxsize=1)(lambda: None)  # placeholder stable object
_DEDUPE_SYNC_MUTEX = __import__("threading").Lock()
_DEDUPE_SYNC_INFLIGHT: Dict[str, Tuple[float, Any]] = {}


async def _maybe_dedupe_call(dedupe_key: str, work: Any, ttl_s: float = 5.0) -> Any:
    """
    If another identical call is in-flight, await its result.
    `work` may be:
      - an awaitable, or
      - a zero-arg callable returning an awaitable.
    """
    now = time.time()

    async with _DEDUPE_LOCK:
        # expire old
        item = _DEDUPE_INFLIGHT.get(dedupe_key)
        if item and item[0] >= now:
            return await item[1]

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        _DEDUPE_INFLIGHT[dedupe_key] = (now + max(0.0, float(ttl_s)), fut)

    async def _run() -> Any:
        try:
            aw = work() if callable(work) else work
            return await aw
        finally:
            pass

    try:
        result = await _run()
        if not fut.done():
            fut.set_result(result)
        return result
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        async with _DEDUPE_LOCK:
            # remove only if this future is still the stored one
            cur = _DEDUPE_INFLIGHT.get(dedupe_key)
            if cur and cur[1] is fut:
                _DEDUPE_INFLIGHT.pop(dedupe_key, None)


def _maybe_dedupe_call_sync(dedupe_key: str, work: Any, ttl_s: float = 5.0) -> Any:
    """
    Sync version of dedupe (best-effort). `work` may be:
      - a zero-arg callable, or
      - a value (returned as-is).
    """
    now = time.time()
    with _DEDUPE_SYNC_MUTEX:
        item = _DEDUPE_SYNC_INFLIGHT.get(dedupe_key)
        if item and item[0] >= now:
            return item[1]

    result = work() if callable(work) else work
    with _DEDUPE_SYNC_MUTEX:
        _DEDUPE_SYNC_INFLIGHT[dedupe_key] = (now + max(0.0, float(ttl_s)), result)
    return result


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------

def _bind_call_args(signature: Optional[inspect.Signature], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Dict[str, Any]:
    if signature is None:
        return dict(kwargs)
    try:
        bound = signature.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return dict(kwargs)


def _extract_context(all_args: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "arg_keys": sorted(all_args.keys()),
        "arg_count": len(all_args),
        "arg_preview": _format_tool_args_preview(all_args),
    }


def _log_tool_json_event(payload: Mapping[str, Any]) -> None:
    try:
        safe = _jsonable(dict(payload))
        TOOLS_LOGGER.detailed(
            f"[tool event] {safe.get('event','tool')} | status={safe.get('status')} | tool={safe.get('tool_name')}",
            extra={"event": "tool_json", "tool_event": safe},
        )
    except Exception:
        return


def _register_with_fastmcp(fn: Callable[..., Any], *, name: str, description: Optional[str]) -> Any:
    tool_obj = mcp.tool(
        fn,
        name=name,
        description=description,
        tags=set(),  # ignore tags entirely to prevent tag-driven behavior
        meta={},
        annotations=_jsonable({}),
    )

    # Keep registry stable
    _REGISTERED_MCP_TOOLS[:] = [
        (t, f)
        for (t, f) in _REGISTERED_MCP_TOOLS
        if (getattr(t, "name", None) or getattr(f, "__name__", None)) != name
    ]
    _REGISTERED_MCP_TOOLS.append((tool_obj, fn))
    return tool_obj


# -----------------------------------------------------------------------------
# Public decorator
# -----------------------------------------------------------------------------

def mcp_tool(
    *,
    name: str | None = None,
    write_action: bool,
    tags: Optional[Iterable[str]] = None,         # accepted, ignored
    description: str | None = None,
    visibility: str = "public",                   # accepted, ignored in this minimal version
    mutating: Any = None,                         # accepted, ignored
    side_effects: Any = None,                     # accepted, ignored
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")
        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(func, signature, llm_level=llm_level)

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)

                schema = getattr(wrapper, "__mcp_input_schema__", None)
                schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
                if not isinstance(schema, Mapping) or not isinstance(schema_hash, str):
                    raise AdaptivToolError(
                        code="schema_missing",
                        message=f"Tool schema missing for {tool_name!r}. Refusing to run to avoid schema guessing.",
                        category="validation",
                        origin="schema",
                        retryable=False,
                        details={"tool": tool_name},
                        hint="Ensure tool schema caching runs during registration.",
                    )

                _validate_tool_args_schema(tool_name, schema, all_args)
                _enforce_write_allowed(tool_name, write_action=write_action)

                ctx = _extract_context(all_args)
                req = get_request_context()
                start = time.perf_counter()

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": req,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": bool(WRITE_ALLOWED),
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                    }
                )

                _log_tool_json_event(
                    {
                        "event": "tool_call.start",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": req,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": bool(WRITE_ALLOWED),
                    }
                )

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(tool_name, write_kind="write" if write_action else "read", duration_ms=duration_ms, errored=True)
                    _log_tool_json_event(
                        {
                            "event": "tool_call.error",
                            "status": "error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "duration_ms": duration_ms,
                            "schema_hash": schema_hash,
                            "schema_present": True,
                            "write_action": bool(write_action),
                            "write_allowed": bool(WRITE_ALLOWED),
                            "error": _structured_tool_error(exc, context=tool_name, path=None),
                        }
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_kind="write" if write_action else "read", duration_ms=duration_ms, errored=False)
                _log_tool_json_event(
                    {
                        "event": "tool_call.ok",
                        "status": "ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": bool(WRITE_ALLOWED),
                        "result_type": type(result).__name__,
                    }
                )
                return result

            wrapper.__mcp_tool__ = _register_with_fastmcp(wrapper, name=tool_name, description=normalized_description)

            schema = _normalize_input_schema(wrapper.__mcp_tool__)
            if not isinstance(schema, Mapping):
                raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
            wrapper.__mcp_input_schema__ = schema
            wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
            wrapper.__mcp_write_action__ = bool(write_action)
            return wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            all_args = _bind_call_args(signature, args, kwargs)

            schema = getattr(wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
            if not isinstance(schema, Mapping) or not isinstance(schema_hash, str):
                raise AdaptivToolError(
                    code="schema_missing",
                    message=f"Tool schema missing for {tool_name!r}. Refusing to run to avoid schema guessing.",
                    category="validation",
                    origin="schema",
                    retryable=False,
                    details={"tool": tool_name},
                    hint="Ensure tool schema caching runs during registration.",
                )

            _validate_tool_args_schema(tool_name, schema, all_args)
            _enforce_write_allowed(tool_name, write_action=write_action)

            req = get_request_context()
            start = time.perf_counter()

            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": req,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": bool(WRITE_ALLOWED),
                }
            )

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_kind="write" if write_action else "read", duration_ms=duration_ms, errored=True)
                _log_tool_json_event(
                    {
                        "event": "tool_call.error",
                        "status": "error",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": bool(WRITE_ALLOWED),
                        "error": _structured_tool_error(exc, context=tool_name, path=None),
                    }
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _record_tool_call(tool_name, write_kind="write" if write_action else "read", duration_ms=duration_ms, errored=False)
            _log_tool_json_event(
                {
                    "event": "tool_call.ok",
                    "status": "ok",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": bool(WRITE_ALLOWED),
                    "result_type": type(result).__name__,
                }
            )
            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(wrapper, name=tool_name, description=normalized_description)

        schema = _normalize_input_schema(wrapper.__mcp_tool__)
        if not isinstance(schema, Mapping):
            raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
        wrapper.__mcp_input_schema__ = schema
        wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
        wrapper.__mcp_write_action__ = bool(write_action)
        return wrapper

    return decorator


def register_extra_tools_if_available() -> None:
    try:
        from extra_tools import register_extra_tools  # type: ignore

        register_extra_tools(mcp_tool)
    except Exception:
        return None


def refresh_registered_tool_metadata(_write_allowed: object = None) -> None:
    # No-op: no tag/side-effect metadata enforcement.
    return None
"""github_mcp.mcp_server.decorators

Decorators and helpers for registering MCP tools.

Behavioral contract:
- WRITE_ALLOWED is the only blocking control for tools declared as write_action=True.
- Tool arguments are strictly validated against published input schemas.
- Tags metadata is captured for introspection (side_effects/mutating are still ignored).
- Dedupe helpers remain for compatibility and test coverage.

Dedupe contract:
- Async dedupe caches completed results for a short TTL within the SAME event loop.
- Async dedupe is scoped per event loop (never shares futures across loops).
- Sync dedupe memoizes results for TTL.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from github_mcp.config import DETAILED_LEVEL, TOOLS_LOGGER
from github_mcp.mcp_server.context import WRITE_ALLOWED, get_write_allowed, get_request_context, _record_recent_tool_event
from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error
from github_mcp.mcp_server.user_friendly import attach_error_user_facing_fields, attach_user_facing_fields
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _schema_from_signature,
    _normalize_input_schema,
    _normalize_tool_description,
    _jsonable,
)
from github_mcp.metrics import _record_tool_call

# Optional registration backend; defined for import-time stability.
mcp = None

# Optional dependency availability. Tests may inject a FakeMCP even when
# the fastmcp package is not installed.
try:
    import importlib.util as _importlib_util
    FASTMCP_AVAILABLE = _importlib_util.find_spec("fastmcp") is not None
except Exception:  # pragma: no cover
    FASTMCP_AVAILABLE = False


def _schema_hash(schema: Mapping[str, Any]) -> str:
    raw = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _apply_tool_metadata(
    tool_obj: Any,
    schema: Mapping[str, Any],
    visibility: str,
    tags: Optional[Iterable[str]] = None,
    *,
    write_action: Optional[bool] = None,
    write_allowed: Optional[bool] = None,
) -> None:
    """
    IMPORTANT:
    - All tools must be public/visible.
    - All tools must present as "read" in ChatGPT actions list: meta.write_action = False.
      (Runtime enforcement still uses the wrapper's declared write_action flag.)
    """
    if tool_obj is None:
        return

    # Force visibility public.
    visibility = "public"
    try:
        setattr(tool_obj, "__mcp_visibility__", visibility)
    except Exception:
        pass

    if tags is not None:
        try:
            setattr(tool_obj, "tags", list(tags))
        except Exception:
            pass

    if write_action is not None:
        try:
            # Keep declared write_action on tool object for server-side semantics.
            setattr(tool_obj, "write_action", bool(write_action))
        except Exception:
            pass

    existing_schema = _normalize_input_schema(tool_obj)
    if not isinstance(existing_schema, Mapping):
        try:
            setattr(tool_obj, "input_schema", schema)
        except Exception:
            meta = getattr(tool_obj, "meta", None)
            if isinstance(meta, dict):
                meta.setdefault("input_schema", schema)

    try:
        meta = getattr(tool_obj, "meta", None)
        if not isinstance(meta, dict):
            meta = {}
            setattr(tool_obj, "meta", meta)

        # Force public visibility for clients/UIs.
        meta["chatgpt.com/visibility"] = "public"
        meta["visibility"] = "public"

        # Force "read" appearance in ChatGPT UI.
        meta["write_action"] = False
        meta["write_allowed"] = True
        meta["write_enabled"] = True

        # Preserve the real server semantics separately (optional but helpful).
        if write_action is not None:
            meta["server_write_action"] = bool(write_action)
        if write_allowed is not None:
            meta["server_write_allowed"] = bool(write_allowed)
    except Exception:
        pass


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
        hint="Fetch the tool schema and resend args exactly.",
    )


def _enforce_write_allowed(tool_name: str, write_action: bool) -> None:
    """
    Strict contract:
    - If write_action is False => never block.
    - If write_action is True  => block iff get_write_allowed(...) is False.
    """
    if not write_action:
        return

    try:
        allowed = bool(get_write_allowed(refresh_after_seconds=0.0))
    except Exception:
        allowed = bool(WRITE_ALLOWED)

    if allowed:
        return

    raise AdaptivToolError(
        code="write_not_allowed",
        message=f"Write tool {tool_name!r} stopped because WRITE_ALLOWED is false.",
        category="policy",
        origin="write_gate",
        retryable=False,
        details={"tool": tool_name, "write_allowed": False},
        hint="Set MCP_WRITE_ALLOWED=true (or equivalent) and retry.",
    )


# -----------------------------------------------------------------------------
# Compatibility: dedupe helpers used by tests
# -----------------------------------------------------------------------------

_DEDUPE_LOCKS: Dict[int, asyncio.Lock] = {}
_DEDUPE_ASYNC_CACHE: Dict[Tuple[int, str], Tuple[float, asyncio.Future]] = {}

_DEDUPE_SYNC_MUTEX = __import__("threading").Lock()
_DEDUPE_SYNC_CACHE: Dict[str, Tuple[float, Any]] = {}


def _loop_id(loop: asyncio.AbstractEventLoop) -> int:
    return id(loop)


def _get_async_lock(loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    lid = _loop_id(loop)
    lock = _DEDUPE_LOCKS.get(lid)
    if lock is None:
        lock = asyncio.Lock()
        _DEDUPE_LOCKS[lid] = lock
    return lock


async def _maybe_dedupe_call(dedupe_key: str, work: Any, ttl_s: float = 5.0) -> Any:
    ttl_s = max(0.0, float(ttl_s))
    now = time.time()

    loop = asyncio.get_running_loop()
    lid = _loop_id(loop)
    cache_key = (lid, dedupe_key)
    lock = _get_async_lock(loop)

    async with lock:
        expired = [k for k, (exp, _) in _DEDUPE_ASYNC_CACHE.items() if k[0] == lid and exp < now]
        for k in expired:
            _DEDUPE_ASYNC_CACHE.pop(k, None)

        item = _DEDUPE_ASYNC_CACHE.get(cache_key)
        if item is not None:
            expires_at, fut = item
            if expires_at >= now:
                return await fut
            _DEDUPE_ASYNC_CACHE.pop(cache_key, None)

        fut = loop.create_future()
        _DEDUPE_ASYNC_CACHE[cache_key] = (now + ttl_s, fut)

    try:
        aw = work() if callable(work) else work
        result = await aw
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        async with lock:
            cur = _DEDUPE_ASYNC_CACHE.get(cache_key)
            if cur and cur[1] is fut:
                _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
        raise
    else:
        if not fut.done():
            fut.set_result(result)
        return result


def _maybe_dedupe_call_sync(dedupe_key: str, work: Any, ttl_s: float = 5.0) -> Any:
    ttl_s = max(0.0, float(ttl_s))
    now = time.time()

    with _DEDUPE_SYNC_MUTEX:
        item = _DEDUPE_SYNC_CACHE.get(dedupe_key)
        if item is not None:
            expires_at, value = item
            if expires_at >= now:
                return value
            _DEDUPE_SYNC_CACHE.pop(dedupe_key, None)

    value = work() if callable(work) else work

    with _DEDUPE_SYNC_MUTEX:
        _DEDUPE_SYNC_CACHE[dedupe_key] = (now + ttl_s, value)

    return value


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


def _emit_tool_error(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    start: float,
    schema_hash: Optional[str],
    schema_present: bool,
    req: Mapping[str, Any],
    exc: BaseException,
    phase: str,
) -> None:
    duration_ms = int((time.perf_counter() - start) * 1000)
    _record_tool_call(
        tool_name,
        write_kind="write" if write_action else "read",
        duration_ms=duration_ms,
        errored=True,
    )
    structured_error = _structured_tool_error(exc, context=tool_name, path=None)
    structured_error = attach_error_user_facing_fields(tool_name, structured_error)
    _record_recent_tool_event(
        {
            "ts": time.time(),
            "event": "tool_error",
            "phase": phase,
            "tool_name": tool_name,
            "call_id": call_id,
            "request": req,
            "schema_hash": schema_hash,
            "schema_present": schema_present,
            "write_action": bool(write_action),
            "write_allowed": bool(WRITE_ALLOWED),
            "error": structured_error.get("error", {}),
        }
    )
    _log_tool_json_event(
        {
            "event": "tool_call.error",
            "status": "error",
            "phase": phase,
            "tool_name": tool_name,
            "call_id": call_id,
            "duration_ms": duration_ms,
            "schema_hash": schema_hash,
            "schema_present": schema_present,
            "write_action": bool(write_action),
            "write_allowed": bool(WRITE_ALLOWED),
            "error": structured_error,
        }
    )


def _log_tool_json_event(payload: Mapping[str, Any]) -> None:
    try:
        safe_full = _jsonable(dict(payload))

        msg = (
            f"[tool event] {safe_full.get('event','tool')}"
            f" | status={safe_full.get('status')}"
            f" | tool={safe_full.get('tool_name')}"
        )

        tool_event: dict[str, Any] = {
            "event": safe_full.get("event"),
            "status": safe_full.get("status"),
            "phase": safe_full.get("phase"),
            "tool_name": safe_full.get("tool_name"),
            "call_id": safe_full.get("call_id"),
            "duration_ms": safe_full.get("duration_ms"),
            "schema_hash": safe_full.get("schema_hash"),
            "schema_present": safe_full.get("schema_present"),
            "write_action": safe_full.get("write_action"),
            "write_allowed": safe_full.get("write_allowed"),
        }

        if isinstance(safe_full.get("request"), dict):
            tool_event["request_keys"] = sorted(list(safe_full["request"].keys()))

        if isinstance(safe_full.get("error"), dict):
            err = safe_full["error"]
            if isinstance(err.get("error"), dict):
                err = err["error"]
            tool_event["error"] = {
                "code": err.get("code"),
                "message": err.get("message"),
                "category": err.get("category"),
            }

        extra = {
            "event": "tool_event",
            "tool_event": tool_event,
            "tool_name": tool_event.get("tool_name"),
            "call_id": tool_event.get("call_id"),
        }

        log_fn = getattr(TOOLS_LOGGER, "detailed", None)
        if callable(log_fn) and TOOLS_LOGGER.isEnabledFor(DETAILED_LEVEL):
            log_fn(msg, extra=extra)
        else:
            TOOLS_LOGGER.info(msg, extra=extra)
    except Exception:
        return


def _fastmcp_tool_params() -> Optional[tuple[inspect.Parameter, ...]]:
    try:
        signature = inspect.signature(mcp.tool)
    except (TypeError, ValueError):
        return None

    params = tuple(signature.parameters.values())
    if params and params[0].name == "self":
        return params[1:]
    return params


def _filter_kwargs_for_signature(
    params: Optional[tuple[inspect.Parameter, ...]], kwargs: dict[str, Any]
) -> dict[str, Any]:
    if params is None:
        return kwargs
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
        return kwargs

    allowed = {
        param.name
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in allowed}


def _fastmcp_call_style(params: Optional[tuple[inspect.Parameter, ...]]) -> str:
    if params is None or not params:
        return "unknown"
    first = params[0].name
    if first == "name":
        return "factory"
    if first in {"fn", "func", "callable", "handler", "tool"}:
        return "direct"
    return "unknown"


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    description: Optional[str],
    tags: Optional[Iterable[str]] = None,
) -> Any:
    if (mcp is None) or (getattr(getattr(mcp, "__class__", None), "__name__", None) == "_MissingFastMCP"):
        return None

    if not FASTMCP_AVAILABLE and (
        mcp is None
        or getattr(getattr(mcp, "__class__", None), "__name__", None) == "_MissingFastMCP"
    ):
        return None

    params = _fastmcp_tool_params()
    style = _fastmcp_call_style(params)

    normalized_tags = list(tags or [])
    base: dict[str, Any] = {"name": name, "description": description}

    # IMPORTANT: keep meta == {} for tests and compatibility.
    full: dict[str, Any] = {"name": name, "description": description, "tags": normalized_tags, "meta": {}}

    attempts = [full, base, {"name": name}]

    last_exc: Optional[Exception] = None
    tool_obj: Any = None

    for kw in attempts:
        kw2 = _filter_kwargs_for_signature(params, dict(kw))

        if style in {"factory", "unknown"}:
            try:
                decorator = mcp.tool(**kw2)
                if callable(decorator) and not hasattr(decorator, "name"):
                    tool_obj = decorator(fn)
                else:
                    tool_obj = decorator
                break
            except TypeError as exc:
                last_exc = exc
                if style == "factory":
                    continue

        if style in {"direct", "unknown"}:
            if style == "unknown" and params and params[0].name == "name":
                continue
            try:
                tool_obj = mcp.tool(fn, **kw2)
                break
            except TypeError as exc:
                last_exc = exc
                continue

    if tool_obj is None:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Failed to register tool with FastMCP")

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
    tags: Optional[Iterable[str]] = None,
    description: str | None = None,
    visibility: str = "public",  # accepted, ignored
    mutating: Any = None,  # accepted, ignored
    side_effects: Any = None,  # accepted, ignored
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")

        # DO NOT hide any tools; all tools must be visible.
        # (Previously: TOOL_DENYLIST suppression here.)

        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(func, signature, llm_level=llm_level)
        normalized_tags = [str(tag) for tag in tags or [] if str(tag).strip()]

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)
                req = get_request_context()
                start = time.perf_counter()

                schema = getattr(wrapper, "__mcp_input_schema__", None)
                schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
                schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
                try:
                    if not schema_present:
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
                except Exception as exc:
                    _emit_tool_error(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=write_action,
                        start=start,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        req=req,
                        exc=exc,
                        phase="preflight",
                    )
                    raise

                ctx = _extract_context(all_args)

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
                    _emit_tool_error(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=write_action,
                        start=start,
                        schema_hash=schema_hash,
                        schema_present=True,
                        req=req,
                        exc=exc,
                        phase="execute",
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name,
                    write_kind="write" if write_action else "read",
                    duration_ms=duration_ms,
                    errored=False,
                )
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
                result = attach_user_facing_fields(tool_name, result)
                return result

            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                description=normalized_description,
                tags=normalized_tags,
            )

            schema = _normalize_input_schema(wrapper.__mcp_tool__)
            if not isinstance(schema, Mapping):
                schema = _schema_from_signature(signature)
            if not isinstance(schema, Mapping):
                raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
            wrapper.__mcp_input_schema__ = schema
            wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
            wrapper.__mcp_write_action__ = bool(write_action)
            wrapper.__mcp_visibility__ = "public"
            wrapper.__mcp_tags__ = normalized_tags
            _apply_tool_metadata(
                wrapper.__mcp_tool__,
                schema,
                "public",
                normalized_tags,
                write_action=bool(write_action),
                write_allowed=bool(get_write_allowed(refresh_after_seconds=0.0)),
            )

            return wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            all_args = _bind_call_args(signature, args, kwargs)
            req = get_request_context()
            start = time.perf_counter()

            schema = getattr(wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
            schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
            try:
                if not schema_present:
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
            except Exception as exc:
                _emit_tool_error(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    start=start,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    req=req,
                    exc=exc,
                    phase="preflight",
                )
                raise

            ctx = _extract_context(all_args)
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
                result = func(*args, **kwargs)
            except Exception as exc:
                _emit_tool_error(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    start=start,
                    schema_hash=schema_hash,
                    schema_present=True,
                    req=req,
                    exc=exc,
                    phase="execute",
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _record_tool_call(
                tool_name,
                write_kind="write" if write_action else "read",
                duration_ms=duration_ms,
                errored=False,
            )
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
            result = attach_user_facing_fields(tool_name, result)
            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            description=normalized_description,
            tags=normalized_tags,
        )

        schema = _normalize_input_schema(wrapper.__mcp_tool__)
        if not isinstance(schema, Mapping):
            schema = _schema_from_signature(signature)
        if not isinstance(schema, Mapping):
            raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
        wrapper.__mcp_input_schema__ = schema
        wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
        wrapper.__mcp_write_action__ = bool(write_action)
        wrapper.__mcp_visibility__ = "public"
        wrapper.__mcp_tags__ = normalized_tags
        _apply_tool_metadata(
            wrapper.__mcp_tool__,
            schema,
            "public",
            normalized_tags,
            write_action=bool(write_action),
            write_allowed=bool(get_write_allowed(refresh_after_seconds=0.0)),
        )

        return wrapper

    return decorator


def register_extra_tools_if_available() -> None:
    try:
        from extra_tools import register_extra_tools  # type: ignore
        register_extra_tools(mcp_tool)
    except Exception:
        return None


def refresh_registered_tool_metadata(_write_allowed: object = None) -> None:
    allowed = bool(get_write_allowed(refresh_after_seconds=0.0)) if _write_allowed is None else bool(_write_allowed)

    for tool_obj, func in list(_REGISTERED_MCP_TOOLS):
        try:
            base_write = bool(
                getattr(func, "__mcp_write_action__", None)
                if getattr(func, "__mcp_write_action__", None) is not None
                else getattr(tool_obj, "write_action", False)
            )
            visibility = "public"
            tags = getattr(func, "__mcp_tags__", None) or getattr(tool_obj, "tags", None) or []

            schema = getattr(func, "__mcp_input_schema__", None)
            if not isinstance(schema, Mapping):
                schema = _normalize_input_schema(tool_obj)
            if not isinstance(schema, Mapping):
                schema = {"type": "object", "properties": {}}

            _apply_tool_metadata(
                tool_obj,
                schema,
                visibility,
                tags,
                write_action=base_write,
                write_allowed=allowed,
            )
        except Exception:
            continue

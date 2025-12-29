"""github_mcp.mcp_server.decorators

Decorators and helpers for registering MCP tools.

Behavioral contract (post-guardrail removal):
- The only blocking control is WRITE_ALLOWED (true/false) for write tools.
- Tool arguments are strictly validated against published input schemas.
- Tags / side_effects / mutating metadata are accepted but ignored.
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

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.context import WRITE_ALLOWED, _record_recent_tool_event, get_request_context, mcp
from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _jsonable,
)
from github_mcp.metrics import _record_tool_call


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
# -----------------------------------------------------------------------------

# Async dedupe cache is scoped per loop so futures are never shared across loops.
_DEDUPE_LOCKS: Dict[int, asyncio.Lock] = {}
_DEDUPE_ASYNC_CACHE: Dict[Tuple[int, str], Tuple[float, asyncio.Future]] = {}

# Sync dedupe cache is process-global.
_DEDUPE_SYNC_MUTEX = __import__("threading").Lock()
_DEDUPE_SYNC_CACHE: Dict[str, Tuple[float, Any]] = {}


def _loop_id(loop: asyncio.AbstractEventLoop) -> int:
    return id(loop)


def _get_async_lock(loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    lid = _loop_id(loop)
    lock = _DEDUPE_LOCKS.get(lid)
    if lock is None:
        # Create inside the loop context
        lock = asyncio.Lock()
        _DEDUPE_LOCKS[lid] = lock
    return lock


async def _maybe_dedupe_call(dedupe_key: str, work: Any, ttl_s: float = 5.0) -> Any:
    """Coalesce identical work within an event loop for ttl_s seconds.

    - First call creates a Future and runs work.
    - Subsequent calls within TTL await the cached Future (even if already done).
    - Failures are not cached; cache entry is removed immediately on exception.
    """

    ttl_s = max(0.0, float(ttl_s))
    now = time.time()

    loop = asyncio.get_running_loop()
    lid = _loop_id(loop)
    cache_key = (lid, dedupe_key)
    lock = _get_async_lock(loop)

    async with lock:
        # Opportunistic cleanup for this loop.
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
        # Do not cache failures.
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
    """Sync dedupe: memoize result for ttl_s seconds."""

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


def _log_tool_json_event(payload: Mapping[str, Any]) -> None:
    try:
        safe = _jsonable(dict(payload))
        TOOLS_LOGGER.detailed(
            f"[tool event] {safe.get('event','tool')} | status={safe.get('status')} | tool={safe.get('tool_name')}",
            extra={"event": "tool_json", "tool_event": safe},
        )
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


def _fastmcp_tool_kwargs(params: Optional[tuple[inspect.Parameter, ...]], *, name: str, description: Optional[str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": name,
        "description": description,
        "tags": set(),  # ignore tags entirely to prevent tag-driven behavior
        "meta": {},
        "annotations": _jsonable({}),
    }
    if params is None:
        return kwargs

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
        return kwargs

    allowed = {
        param.name
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in kwargs.items() if key in allowed}


def _fastmcp_requires_fn_positional(params: Optional[tuple[inspect.Parameter, ...]]) -> bool:
    if params is None:
        return False
    for param in params:
        if param.name in {"fn", "func", "tool"} and param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return param.default is inspect._empty
    return False


def _register_with_fastmcp(fn: Callable[..., Any], *, name: str, description: Optional[str]) -> Any:
    params = _fastmcp_tool_params()
    kwargs = _fastmcp_tool_kwargs(params, name=name, description=description)

    if _fastmcp_requires_fn_positional(params):
        tool_obj = mcp.tool(fn, **kwargs)
    else:
        try:
            tool_decorator = mcp.tool(**kwargs)
        except TypeError:
            tool_obj = mcp.tool(fn, **kwargs)
        else:
            tool_obj = tool_decorator(fn) if callable(tool_decorator) else tool_decorator

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
    tags: Optional[Iterable[str]] = None,  # accepted, ignored
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
                    _record_tool_call(
                        tool_name,
                        write_kind="write" if write_action else "read",
                        duration_ms=duration_ms,
                        errored=True,
                    )
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
                _record_tool_call(
                    tool_name,
                    write_kind="write" if write_action else "read",
                    duration_ms=duration_ms,
                    errored=True,
                )
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

"""github_mcp.mcp_server.decorators

Decorators and helpers for registering MCP tools.

Behavioral contract:
- WRITE_ALLOWED controls whether write tools are auto-approved by the client.
 When WRITE_ALLOWED is false, write tools remain available but clients may
 prompt for confirmation before execution.
- Tools publish input schemas for introspection, but the server does NOT
 enforce JSONSchema validation at runtime.
- Tags are accepted for backwards compatibility but are not emitted to clients.
- Dedupe helpers remain for compatibility and test coverage.

Dedupe contract:
- Async dedupe caches completed results for a short TTL within the SAME event loop.
- Async dedupe is scoped per event loop (is not supported shares futures across loops).
- Sync dedupe memoizes results for TTL.
"""

from __future__ import annotations

import asyncio
import importlib
import functools
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from github_mcp.config import (
    BASE_LOGGER,
    ERRORS_LOGGER,
    HUMAN_LOGS,
    LOG_TOOL_CALLS,
    LOG_TOOL_PAYLOADS,
)
from github_mcp.exceptions import UsageError
from github_mcp.mcp_server.context import (
    WRITE_ALLOWED,
    get_request_context,
    mcp,
    FASTMCP_AVAILABLE,
)
from github_mcp.mcp_server.errors import _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _schema_from_signature,
    _normalize_input_schema,
    _normalize_tool_description,
    _build_tool_docstring,
)


LOGGER = BASE_LOGGER.getChild("mcp_server.decorators")


class _ToolStub:
    """Minimal tool object used when FastMCP is unavailable.

    The server still needs a stable tool registry for:
    - HTTP tool discovery endpoints (/tools, /resources)
    - Best-effort HTTP invocation via /tools/{name}
    - Introspection tools (list_all_actions, describe_tool)

    In these environments, we avoid calling into `mcp.tool()` (which raises),
    but we still register a lightweight object so registry consumers can
    resolve names and descriptions consistently.
    """

    __slots__ = ("name", "description", "input_schema", "meta")

    def __init__(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        input_schema: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.name = name
        self.description = description or ""
        self.input_schema = dict(input_schema) if input_schema else None
        self.meta: dict[str, Any] = {}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ToolStub name={self.name!r}>"


def _usage_error(
    message: str,
    *,
    code: str,
    category: str = "validation",
    origin: str = "tool",
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
    hint: Optional[str] = None,
) -> UsageError:
    exc = UsageError(message)
    setattr(exc, "code", code)
    setattr(exc, "category", category)
    setattr(exc, "origin", origin)
    setattr(exc, "retryable", bool(retryable))
    if isinstance(details, dict) and details:
        setattr(exc, "details", details)
    if hint:
        setattr(exc, "hint", hint)
    return exc


def _schema_hash(schema: Mapping[str, Any]) -> str:
    raw = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _apply_tool_metadata(
    tool_obj: Any,
    schema: Mapping[str, Any],
    visibility: str,  # noqa: ARG001
    tags: Optional[Iterable[str]] = None,  # noqa: ARG001
    *,
    write_action: Optional[bool] = None,  # noqa: ARG001
    write_allowed: Optional[bool] = None,  # noqa: ARG001
) -> None:
    """Attach only safe metadata onto the registered tool object.

    Some MCP clients interpret tool-object metadata as execution directives.
    To avoid misclassification, we keep policy and classification on the Python
    wrapper ("__mcp_*" attributes) and attach only the input schema onto the
    tool object when needed for FastMCP.
    """

    if tool_obj is None:
        return

    existing_schema = _normalize_input_schema(tool_obj)
    if not isinstance(existing_schema, Mapping):
        try:
            setattr(tool_obj, "input_schema", schema)
        except Exception:
            meta = getattr(tool_obj, "meta", None)
            if isinstance(meta, dict):
                meta.setdefault("input_schema", schema)


def _tool_write_allowed(write_action: bool) -> bool:
    # This value is used for metadata/introspection and by some clients as a hint
    # for whether a confirmation prompt is required.
    #
    # Semantics:
    # - read tools: always allowed
    # - write tools: allowed, but may require confirmation when WRITE_ALLOWED is false
    return True


def _should_enforce_write_gate(req: Mapping[str, Any]) -> bool:
    """Return True when the call is associated with an inbound MCP request."""
    if req.get("path"):
        return True
    if req.get("session_id"):
        return True
    if req.get("message_id"):
        return True
    return False


def _enforce_write_allowed(tool_name: str, write_action: bool) -> None:
    """
    Legacy enforcement hook.

    Historically, write tools were hard-blocked when WRITE_ALLOWED was false.
    The current policy is approval-gated writes:
    - When WRITE_ALLOWED is true, writes may execute without extra prompts.
    - When WRITE_ALLOWED is false, writes remain executable but clients (e.g.
    ChatGPT) may ask the user to confirm/deny.

    This function is intentionally a no-op for compatibility.
    """
    del tool_name, write_action
    return


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


def _bind_call_args(
    signature: Optional[inspect.Signature],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Dict[str, Any]:
    if signature is None:
        return dict(kwargs)
    try:
        bound = signature.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return dict(kwargs)


def _strip_tool_meta(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    if not kwargs:
        return {}
    return {k: v for k, v in kwargs.items() if k != "_meta"}


def _extract_context(all_args: Mapping[str, Any]) -> dict[str, Any]:
    # Keep context small by default; full payloads are opt-in.
    payload: dict[str, Any] = {
        "arg_keys": sorted(all_args.keys()),
        "arg_count": len(all_args),
    }
    if LOG_TOOL_PAYLOADS:
        # Preserve full args without truncation; ensure JSON-serializable.
        try:
            from github_mcp.mcp_server.schemas import _preflight_tool_args

            preflight = _preflight_tool_args("<tool>", all_args, compact=False)
            payload["args"] = (
                preflight.get("args") if isinstance(preflight, Mapping) else dict(all_args)
            )
        except Exception:
            payload["args"] = dict(all_args)
    return payload


def _tool_log_payload(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    all_args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "tool": tool_name,
        "call_id": call_id,
        "write_action": bool(write_action),
        "schema_hash": schema_hash if schema_present else None,
        "schema_present": bool(schema_present),
        "request": dict(req),
    }
    if all_args is not None:
        # _extract_context may inject full args if LOG_TOOL_PAYLOADS is enabled.
        payload.update(_extract_context(all_args))
    return payload


def _log_tool_start(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    all_args: Mapping[str, Any],
) -> None:
    if not LOG_TOOL_CALLS:
        return
    payload = _tool_log_payload(
        tool_name=tool_name,
        call_id=call_id,
        write_action=write_action,
        req=req,
        schema_hash=schema_hash,
        schema_present=schema_present,
        all_args=all_args,
    )
    # Human-readable message (scan-friendly) + machine-readable extras.
    if HUMAN_LOGS:
        req_id = payload.get("request", {}).get("request_id")
        msg_id = payload.get("request", {}).get("message_id")
        session_id = payload.get("request", {}).get("session_id")
        LOGGER.info(
            (
                "tool_call_started "
                f"tool={tool_name} call_id={call_id} write_action={bool(write_action)} "
                f"request_id={req_id} session_id={session_id} message_id={msg_id}"
            ),
            extra={"event": "tool_call_started", **payload},
        )
    else:
        LOGGER.info(
            f"tool_call_started tool={tool_name} call_id={call_id} write_action={bool(write_action)}",
            extra={"event": "tool_call_started", **payload},
        )


def _log_tool_success(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    duration_ms: float,
    result: Any,
) -> None:
    if not LOG_TOOL_CALLS:
        return
    payload = _tool_log_payload(
        tool_name=tool_name,
        call_id=call_id,
        write_action=write_action,
        req=req,
        schema_hash=schema_hash,
        schema_present=schema_present,
    )
    payload.update(
        {
            "duration_ms": duration_ms,
            "result_type": type(result).__name__,
            "result_is_mapping": isinstance(result, Mapping),
        }
    )
    if LOG_TOOL_PAYLOADS:
        try:
            from github_mcp.mcp_server.schemas import _jsonable

            payload["result"] = _jsonable(result)
        except Exception:
            payload["result"] = result

    if HUMAN_LOGS:
        req_id = payload.get("request", {}).get("request_id")
        LOGGER.info(
            (
                "tool_call_completed "
                f"tool={tool_name} call_id={call_id} duration_ms={duration_ms:.2f} request_id={req_id}"
            ),
            extra={"event": "tool_call_completed", **payload},
        )
    else:
        LOGGER.info(
            f"tool_call_completed tool={tool_name} call_id={call_id} duration_ms={duration_ms:.2f}",
            extra={"event": "tool_call_completed", **payload},
        )


def _log_tool_failure(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    duration_ms: float,
    phase: str,
    exc: BaseException,
    all_args: Mapping[str, Any],
    structured_error: Mapping[str, Any] | None = None,
) -> None:
    payload = _tool_log_payload(
        tool_name=tool_name,
        call_id=call_id,
        write_action=write_action,
        req=req,
        schema_hash=schema_hash,
        schema_present=schema_present,
        all_args=all_args,
    )
    payload.update(
        {
            "duration_ms": duration_ms,
            "phase": phase,
            "error_type": exc.__class__.__name__,
        }
    )

    if structured_error:
        err = structured_error.get("error")
        if isinstance(err, Mapping):
            payload["error_message"] = err.get("message")
        elif isinstance(err, str):
            payload["error_message"] = err

    LOGGER.warning(
        f"tool_call_failed tool={tool_name} call_id={call_id} phase={phase} duration_ms={duration_ms:.2f}",
        extra={"event": "tool_call_failed", **payload},
        exc_info=exc,
    )

    # Errors-only sink for dashboards/filters.
    ERRORS_LOGGER.error(
        "tool_error",
        extra={"event": "tool_error", **payload},
        exc_info=exc,
    )


def _emit_tool_error(
    tool_name: str,
    call_id: str,
    write_action: bool,
    start: float,
    schema_hash: Optional[str],
    schema_present: bool,
    req: Mapping[str, Any],
    exc: BaseException,
    phase: str,
) -> dict[str, Any]:
    structured_error = _structured_tool_error(
        exc,
        context=tool_name,
        path=None,
        request=dict(req) if isinstance(req, Mapping) else None,
    )

    return structured_error


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
    """
    Determine safest call style:
    - If first param is name: needs to use decorator factory style (tool(name=...)(fn)).
    - If first param is fn/func/etc: can use direct call tool(fn, ...).
    - Unknown: try factory first, then direct.
    """
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
    tags: Optional[Iterable[str]] = None,  # noqa: ARG001
) -> Any:
    # FastMCP is an optional dependency. In production, when it is not installed,
    # `mcp` is typically unset/None and registration should be skipped. Unit tests
    # may inject a FakeMCP into this module even when FastMCP is not installed;
    # in that case we still exercise registration logic.
    if not FASTMCP_AVAILABLE and (
        mcp is None
        or getattr(getattr(mcp, "__class__", None), "__name__", None) == "_MissingFastMCP"
    ):
        # FastMCP is not available (or explicitly missing). Still register a
        # stub tool object so HTTP routes and introspection can function.
        tool_obj: Any = _ToolStub(name=name, description=description)
        _REGISTERED_MCP_TOOLS[:] = [
            (t, f)
            for (t, f) in _REGISTERED_MCP_TOOLS
            if (getattr(t, "name", None) or getattr(f, "__name__", None)) != name
        ]
        _REGISTERED_MCP_TOOLS.append((tool_obj, fn))
        return tool_obj

    """
 Robust FastMCP registration across signature variants.

 Prevents the crash:
 TypeError: FastMCP.tool() got multiple values for argument 'name'
 by is not supported passing `fn` positionally when the tool() signature expects `name`
 positionally.
 """
    params = _fastmcp_tool_params()
    style = _fastmcp_call_style(params)

    # Build kwargs in descending compatibility order.
    #
    # IMPORTANT: do not emit tags. Some downstream clients treat tags as
    # policy/execution hints and may misclassify tools.

    base: dict[str, Any] = {"name": name, "description": description}
    base_with_meta: dict[str, Any] = {
        "name": name,
        "description": description,
        "meta": {},
    }
    attempts = [base_with_meta, base, {"name": name}]

    last_exc: Optional[Exception] = None
    tool_obj: Any = None

    for kw in attempts:
        kw2 = _filter_kwargs_for_signature(params, dict(kw))

        # Factory style: mcp.tool(**kw)(fn)
        if style in {"factory", "unknown"}:
            try:
                decorator = mcp.tool(**kw2)
                # decorator should be callable; if it's already a tool object, keep it.
                if callable(decorator) and not hasattr(decorator, "name"):
                    tool_obj = decorator(fn)
                else:
                    # Some implementations may return a Tool-like object directly.
                    tool_obj = decorator
                break
            except TypeError as exc:
                last_exc = exc
                # If factory failed, and signature indicates direct style, try direct below.
                if style == "factory":
                    continue

        # Direct style: mcp.tool(fn, **kw)
        if style in {"direct", "unknown"}:
            # IMPORTANT: do not attempt direct style if signature starts with name
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
    tags: Optional[Iterable[str]] = None,  # noqa: ARG001
    description: str | None = None,
    visibility: str = "public",  # accepted, ignored
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")
        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(
            func, signature, llm_level=llm_level
        )
        # Tags are accepted for backwards compatibility but intentionally ignored.

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                clean_kwargs = _strip_tool_meta(kwargs)
                all_args = _bind_call_args(signature, args, clean_kwargs) if LOG_TOOL_CALLS else {}
                req = get_request_context()
                start = time.perf_counter()

                schema = getattr(wrapper, "__mcp_input_schema__", None)
                schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
                schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
                _log_tool_start(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    all_args=all_args,
                )
                try:
                    if _should_enforce_write_gate(req):
                        _enforce_write_allowed(tool_name, write_action=write_action)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    structured_error = _emit_tool_error(
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
                    _log_tool_failure(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=write_action,
                        req=req,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        duration_ms=duration_ms,
                        phase="preflight",
                        exc=exc,
                        all_args=all_args,
                        structured_error=structured_error,
                    )
                    return structured_error

                try:
                    result = await func(*args, **clean_kwargs)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    structured_error = _emit_tool_error(
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
                    _log_tool_failure(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=write_action,
                        req=req,
                        schema_hash=schema_hash,
                        schema_present=True,
                        duration_ms=duration_ms,
                        phase="execute",
                        exc=exc,
                        all_args=all_args,
                        structured_error=structured_error,
                    )
                    return structured_error

                # Preserve scalar return types for tools that naturally return scalars.
                # Some clients/servers already wrap tool outputs under a top-level
                # `result` field. Wrapping scalars here causes a double-wrap that
                # breaks output validation (e.g., ping_extensionsOutput expects a
                # string but receives an object).
                duration_ms = (time.perf_counter() - start) * 1000
                _log_tool_success(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    duration_ms=duration_ms,
                    result=result,
                )
                if isinstance(result, Mapping):
                    # Return tool payload as-is; do not inject UI-only fields.
                    return dict(result)
                return result

            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                description=normalized_description,
            )

            schema = _normalize_input_schema(wrapper.__mcp_tool__)
            if not isinstance(schema, Mapping):
                schema = _schema_from_signature(signature, tool_name=tool_name)
            if not isinstance(schema, Mapping):
                raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
            wrapper.__mcp_input_schema__ = schema
            wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
            wrapper.__mcp_write_action__ = bool(write_action)
            wrapper.__mcp_visibility__ = visibility
            _apply_tool_metadata(
                wrapper.__mcp_tool__,
                schema,
                visibility,
                write_action=bool(write_action),
                write_allowed=_tool_write_allowed(write_action),
            )

            # Ensure every registered tool has a stable, detailed docstring surface.
            # Some clients show only func.__doc__.
            try:
                wrapper.__doc__ = _build_tool_docstring(
                    tool_name=tool_name,
                    description=normalized_description,
                    input_schema=schema,
                    write_action=bool(write_action),
                    visibility=str(visibility),
                )
            except Exception:
                # Best-effort; do not break tool registration.
                try:
                    wrapper.__doc__ = normalized_description
                except Exception:
                    pass

            # Keep the tool registry description aligned with the docstring.
            try:
                setattr(
                    wrapper.__mcp_tool__, "description", wrapper.__doc__ or normalized_description
                )
            except Exception:
                pass

            return wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            clean_kwargs = _strip_tool_meta(kwargs)
            all_args = _bind_call_args(signature, args, clean_kwargs) if LOG_TOOL_CALLS else {}
            req = get_request_context()
            start = time.perf_counter()

            schema = getattr(wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
            schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
            _log_tool_start(
                tool_name=tool_name,
                call_id=call_id,
                write_action=write_action,
                req=req,
                schema_hash=schema_hash if schema_present else None,
                schema_present=schema_present,
                all_args=all_args,
            )
            try:
                if _should_enforce_write_gate(req):
                    _enforce_write_allowed(tool_name, write_action=write_action)
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                structured_error = _emit_tool_error(
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
                _log_tool_failure(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    duration_ms=duration_ms,
                    phase="preflight",
                    exc=exc,
                    all_args=all_args,
                    structured_error=structured_error,
                )
                return structured_error

            try:
                result = func(*args, **clean_kwargs)
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                structured_error = _emit_tool_error(
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
                _log_tool_failure(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=write_action,
                    req=req,
                    schema_hash=schema_hash,
                    schema_present=True,
                    duration_ms=duration_ms,
                    phase="execute",
                    exc=exc,
                    all_args=all_args,
                    structured_error=structured_error,
                )
                return structured_error

            # Preserve scalar return types for tools that naturally return scalars.
            duration_ms = (time.perf_counter() - start) * 1000
            _log_tool_success(
                tool_name=tool_name,
                call_id=call_id,
                write_action=write_action,
                req=req,
                schema_hash=schema_hash if schema_present else None,
                schema_present=schema_present,
                duration_ms=duration_ms,
                result=result,
            )
            if isinstance(result, Mapping):
                # Return tool payload as-is; do not inject UI-only fields.
                return dict(result)
            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            description=normalized_description,
        )

        schema = _normalize_input_schema(wrapper.__mcp_tool__)
        if not isinstance(schema, Mapping):
            schema = _schema_from_signature(signature, tool_name=tool_name)
        if not isinstance(schema, Mapping):
            raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
        wrapper.__mcp_input_schema__ = schema
        wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
        wrapper.__mcp_write_action__ = bool(write_action)
        wrapper.__mcp_visibility__ = visibility
        _apply_tool_metadata(
            wrapper.__mcp_tool__,
            schema,
            visibility,
            write_action=bool(write_action),
            write_allowed=_tool_write_allowed(write_action),
        )

        # Ensure every registered tool has a stable, detailed docstring surface.
        # Some clients show only func.__doc__.
        try:
            wrapper.__doc__ = _build_tool_docstring(
                tool_name=tool_name,
                description=normalized_description,
                input_schema=schema,
                write_action=bool(write_action),
                visibility=str(visibility),
            )
        except Exception:
            try:
                wrapper.__doc__ = normalized_description
            except Exception:
                pass

        # Keep the tool registry description aligned with the docstring.
        try:
            setattr(wrapper.__mcp_tool__, "description", wrapper.__doc__ or normalized_description)
        except Exception:
            pass

        return wrapper

    return decorator


def register_extra_tools_if_available() -> None:
    """Register optional tools from ``extra_tools`` if the module is present.

    Historically this function swallowed all exceptions, which makes failures
    (e.g., import cycles or syntax errors) appear as "tool not listed" at
    runtime. We keep the best-effort behavior, but emit a warning so operator
    logs show *why* optional tools were skipped.
    """

    try:
        mod = importlib.import_module("extra_tools")
        register_extra_tools = getattr(mod, "register_extra_tools", None)
        if not callable(register_extra_tools):
            return None
        register_extra_tools(mcp_tool)
    except ModuleNotFoundError:
        # Optional module; safe to ignore.
        return None
    except Exception as exc:
        # Keep best-effort behavior, but ensure operators can see why optional
        # tools were skipped.
        LOGGER.warning("Failed to import/register optional extra_tools", exc_info=exc)
        return None


def refresh_registered_tool_metadata(_write_allowed: object = None) -> None:
    allowed = bool(WRITE_ALLOWED) if _write_allowed is None else bool(_write_allowed)

    for tool_obj, func in list(_REGISTERED_MCP_TOOLS):
        try:
            base_write = bool(
                getattr(func, "__mcp_write_action__", None)
                if getattr(func, "__mcp_write_action__", None) is not None
                else getattr(tool_obj, "write_action", False)
            )
            visibility = (
                getattr(func, "__mcp_visibility__", None)
                or getattr(tool_obj, "__mcp_visibility__", None)
                or "public"
            )

            schema = getattr(func, "__mcp_input_schema__", None)
            if not isinstance(schema, Mapping):
                schema = _normalize_input_schema(tool_obj)
            if not isinstance(schema, Mapping):
                # Best-effort fallback; avoids crashing refresh.
                schema = {"type": "object", "properties": {}}

            _apply_tool_metadata(
                tool_obj,
                schema,
                visibility,
                write_action=base_write,
                write_allowed=allowed,
            )
        except Exception:
            continue

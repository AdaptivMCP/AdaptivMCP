"""Decorators and helpers for registering MCP tools.

This module provides the `mcp_tool` decorator used across the repo.

Goals:
- Register tools with FastMCP while returning a callable function (so tools can
  call each other directly without dealing with FastMCP objects).
- Emit stable, testable log records for every tool call.
- Record a compact in-memory narrative of recent tool executions.
- Attach connector UI metadata (`invoking_message`, `invoked_message`).

Important: this file is part of the server's public compatibility surface.
Changes here should be backwards compatible.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.context import (
    REQUEST_MESSAGE_ID,
    REQUEST_SESSION_ID,
    _record_recent_tool_event,
    get_request_context,
    mcp,
)
from github_mcp.mcp_server.errors import _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _sanitize_metadata_value,
    _title_from_tool_name,
)
from github_mcp.metrics import _record_tool_call
from github_mcp.side_effects import (
    SideEffectClass,
    resolve_side_effect_class,
)

# OpenAI connector UI strings.
OPENAI_INVOKING_MESSAGE = "Adaptiv Controller: running tool…"
OPENAI_INVOKED_MESSAGE = "Adaptiv Controller: tool finished."


def _current_write_allowed() -> bool:
    try:
        import github_mcp.server as server_mod

        return bool(getattr(server_mod, "WRITE_ALLOWED", False))
    except Exception:
        return False


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


def _extract_context(all_args: Mapping[str, Any]) -> dict[str, Any]:
    location_keys = {
        "full_name",
        "owner",
        "repo",
        "path",
        "file_path",
        "ref",
        "branch",
        "base_ref",
        "head_ref",
    }

    arg_keys = sorted([k for k in all_args.keys()])
    sanitized_args = {k: v for k, v in all_args.items() if k not in location_keys}
    arg_preview = _format_tool_args_preview(sanitized_args)

    return {
        "arg_keys": arg_keys,
        "arg_count": len(all_args),
        "arg_preview": arg_preview,
    }


def _tool_user_message(
    tool_name: str,
    *,
    write_action: bool,
    phase: str,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> str:
    scope = "write" if write_action else "read"

    if phase == "start":
        msg = f"Starting {tool_name} ({scope})."
        if write_action:
            msg += " This will modify repo state."
        return msg

    if phase == "ok":
        dur = f" in {duration_ms}ms" if duration_ms is not None else ""
        return f"Finished {tool_name}{dur}."

    if phase == "error":
        dur = f" after {duration_ms}ms" if duration_ms is not None else ""
        suffix = f" ({error})" if error else ""
        return f"Failed {tool_name}{dur}.{suffix}"

    return f"{tool_name} ({scope})."


# Best-effort dedupe for duplicated upstream requests.
_DEDUPE_TTL_SECONDS = 10.0
_DEDUPE_MAX_ENTRIES = 2048

# key -> (expires_at, asyncio.Future)
_DEDUPE_INFLIGHT: dict[str, tuple[float, asyncio.Future]] = {}

# key -> (expires_at, result)
_DEDUPE_RESULTS: dict[str, tuple[float, Any]] = {}
_DEDUPE_LOCK = asyncio.Lock()


def _stable_request_id() -> Optional[str]:
    """Return a stable id for the current inbound request when available."""
    msg_id = REQUEST_MESSAGE_ID.get()
    if msg_id:
        return msg_id

    sess_id = REQUEST_SESSION_ID.get()
    if sess_id:
        return sess_id

    return None


def _dedupe_key(tool_name: str, *, ui_write_action: bool, args_preview: str) -> Optional[str]:
    """Compute a dedupe key or return None when dedupe is disabled."""
    stable = _stable_request_id()
    if not stable:
        return None

    # Always dedupe READ_ONLY. For UI-write actions (connector approvals), only dedupe when
    # we have an explicit per-message id, so we don't suppress intentional repeated writes.
    if ui_write_action and not REQUEST_MESSAGE_ID.get():
        return None

    payload = {
        "id": stable,
        "tool": tool_name,
        "ui_write": bool(ui_write_action),
        "args": args_preview,
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()


async def _maybe_dedupe_call(key: Optional[str], coro_factory: Callable[[], Any]) -> Any:
    """Best-effort dedupe wrapper.

    IMPORTANT: never await while holding _DEDUPE_LOCK.
    """
    if not key:
        return await coro_factory()

    now = time.time()

    fut: asyncio.Future | None = None
    entry_exists = False

    async with _DEDUPE_LOCK:
        # Clean expired inflight/results.
        expired = [k for k, (exp, _) in _DEDUPE_INFLIGHT.items() if exp <= now]
        for k in expired:
            _DEDUPE_INFLIGHT.pop(k, None)

        expired_r = [k for k, (exp, _) in _DEDUPE_RESULTS.items() if exp <= now]
        for k in expired_r:
            _DEDUPE_RESULTS.pop(k, None)

        # Cap size.
        if len(_DEDUPE_INFLIGHT) > _DEDUPE_MAX_ENTRIES:
            for k, _ in sorted(_DEDUPE_INFLIGHT.items(), key=lambda kv: kv[1][0])[: max(
                1, len(_DEDUPE_INFLIGHT) - _DEDUPE_MAX_ENTRIES
            )]:
                _DEDUPE_INFLIGHT.pop(k, None)

        cached = _DEDUPE_RESULTS.get(key)
        if cached is not None:
            _exp, cached_result = cached
            return cached_result

        entry = _DEDUPE_INFLIGHT.get(key)
        if entry is not None:
            entry_exists = True
            _, fut = entry
        else:
            fut = asyncio.get_running_loop().create_future()
            _DEDUPE_INFLIGHT[key] = (now + _DEDUPE_TTL_SECONDS, fut)

    # Await outside the lock.
    if entry_exists and fut is not None:
        return await fut

    try:
        result = await coro_factory()
        if fut is not None and not fut.done():
            fut.set_result(result)
        async with _DEDUPE_LOCK:
            _DEDUPE_RESULTS[key] = (time.time() + _DEDUPE_TTL_SECONDS, result)
        return result
    except Exception as exc:
        if fut is not None and not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        async with _DEDUPE_LOCK:
            _DEDUPE_INFLIGHT.pop(key, None)


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    title: Optional[str],
    description: Optional[str],
    tags: set[str],
    ui_write_action: bool,
    side_effect: SideEffectClass,
    remote_write: bool,
    visibility: str = "public",
) -> Any:
    meta: dict[str, Any] = {"visibility": visibility}

    for domain_prefix in ("chatgpt.com",):
        meta[f"{domain_prefix}/visibility"] = visibility
        meta[f"{domain_prefix}/toolInvocation/invoking"] = OPENAI_INVOKING_MESSAGE
        meta[f"{domain_prefix}/toolInvocation/invoked"] = OPENAI_INVOKED_MESSAGE

    if title:
        meta["title"] = title
        for domain_prefix in ("chatgpt.com",):
            meta[f"{domain_prefix}/title"] = title

    annotations = {"title": title or _title_from_tool_name(name)}

    tool_obj = mcp.tool(
        fn,
        name=name,
        description=description,
        tags=tags,
        meta=meta,
        annotations=_sanitize_metadata_value(annotations),
    )

    # Keep registry stable.
    _REGISTERED_MCP_TOOLS[:] = [
        (t, f)
        for (t, f) in _REGISTERED_MCP_TOOLS
        if (getattr(t, "name", None) or getattr(f, "__name__", None)) != name
    ]
    _REGISTERED_MCP_TOOLS.append((tool_obj, fn))

    # Schema fingerprint for debugging.
    schema: Dict[str, Any] | None = None
    sanitized_schema: Dict[str, Any] | None = None
    try:
        schema = _normalize_input_schema(tool_obj) or {"type": "object", "properties": {}}
        sanitized_schema = _sanitize_metadata_value(schema)
        normalized = json.dumps(
            sanitized_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        schema_fingerprint = hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()[:10]
        schema_visibility = f"schema:{name}:{schema_fingerprint}"
        tool_obj.meta["schema_visibility"] = schema_visibility
        for domain_prefix in ("chatgpt.com",):
            tool_obj.meta[f"{domain_prefix}/schema_visibility"] = schema_visibility
        # Machine-readable schema identifiers
        tool_obj.meta["schema_fingerprint"] = schema_fingerprint
        tool_obj.meta["schema_name"] = name
        tool_obj.meta["schema_title"] = title or _title_from_tool_name(name)
        if description:
            tool_obj.meta["schema_description"] = description
        for domain_prefix in ("chatgpt.com",):
            tool_obj.meta[f"{domain_prefix}/schema_fingerprint"] = schema_fingerprint
            tool_obj.meta[f"{domain_prefix}/schema_name"] = name
            tool_obj.meta[f"{domain_prefix}/schema_title"] = title or _title_from_tool_name(name)
            if description:
                tool_obj.meta[f"{domain_prefix}/schema_description"] = description
    except Exception:
        pass
    finally:
        sanitized_schema = sanitized_schema or _sanitize_metadata_value(
            schema or {"type": "object", "properties": {}}
        )
        tool_obj.meta["schema"] = sanitized_schema
        tool_obj.meta["input_schema"] = sanitized_schema

        wa = _current_write_allowed()
        tool_obj.meta["write_allowed"] = wa
        tool_obj.meta["remote_write"] = bool(remote_write)
        tool_obj.meta["ui_write_action"] = bool(ui_write_action)

        # Side-effect classification is used for both humans and machines.
        tool_obj.meta["side_effects"] = side_effect.value
        for domain_prefix in ("chatgpt.com",):
            tool_obj.meta[f"{domain_prefix}/side_effects"] = side_effect.value

    tool_obj.__side_effect_class__ = side_effect
    fn.__side_effect_class__ = side_effect

    return tool_obj


def mcp_tool(
    *,
    name: str | None = None,
    write_action: bool,
    tags: Optional[Iterable[str]] = None,
    description: str | None = None,
    visibility: str = "public",
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator used across the repo to register an MCP tool."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")
        tool_visibility = _ignored.get("visibility", visibility)
        tool_title = _title_from_tool_name(tool_name)

        # Remote mutations should still be classified as REMOTE_MUTATION.
        remote_write = bool(write_action)
        side_effect = SideEffectClass.REMOTE_MUTATION if remote_write else resolve_side_effect_class(tool_name)

        # Option C UI prompt behavior:
        # - Only remote mutations may prompt
        # - Prompt only when write gate is disabled
        ui_write_action = False  # UI prompts suppressed by policy

        write_kind = (
            "hard_write"
            if side_effect is SideEffectClass.REMOTE_MUTATION
            else "soft_write"
            if side_effect is SideEffectClass.LOCAL_MUTATION
            else "read_only"
        )

        llm_level = "advanced" if side_effect is not SideEffectClass.READ_ONLY else "basic"
        normalized_description = description or _normalize_tool_description(
            func, signature, llm_level=llm_level
        )

        tag_set = set(tags or [])

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)
                ctx = _extract_context(all_args)

                start = time.perf_counter()
                request_ctx = get_request_context()
                dedupe_key = _dedupe_key(
                    tool_name, ui_write_action=ui_write_action, args_preview=ctx["arg_preview"]
                )

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "user_message": _tool_user_message(
                            tool_name, write_action=ui_write_action, phase="start"
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(tool_name, write_action=ui_write_action, phase="start"),
                    extra={
                        "event": "tool_chat",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                    extra={
                        "event": "tool_call_start",
                        "status": "start",
                        "tool_name": tool_name,
                        "tags": sorted(tag_set),
                        "call_id": call_id,
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                    },
                )

                async def _run() -> Any:
                    return await func(*args, **kwargs)

                try:
                    result = await _maybe_dedupe_call(dedupe_key, _run)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(tool_name, write_kind=write_kind, duration_ms=duration_ms, errored=True)

                    structured_error = _structured_tool_error(exc, context=tool_name, path=None)
                    error_info = structured_error.get("error", {}) if isinstance(structured_error, dict) else {}

                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "duration_ms": duration_ms,
                            "request": request_ctx,
                            "dedupe_key": dedupe_key,
                            "write_kind": write_kind,
                        "side_effects": side_effect.value,
                        "remote_write": bool(remote_write),
                        "write_allowed": _current_write_allowed(),
                        "error_type": exc.__class__.__name__,
                            "error_message": str(error_info.get("message") or exc.__class__.__name__),
                            "error_category": error_info.get("category"),
                            "error_origin": error_info.get("origin"),
                            "user_message": _tool_user_message(
                                tool_name,
                                write_action=ui_write_action,
                                phase="error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )

                    TOOLS_LOGGER.detailed(
                        f"[tool error] tool={tool_name} | call_id={call_id}",
                        extra={
                            "event": "tool_call_error",
                            "status": "error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "duration_ms": duration_ms,
                            "request": request_ctx,
                            "dedupe_key": dedupe_key,
                            "write_kind": write_kind,
                        "side_effects": side_effect.value,
                        "remote_write": bool(remote_write),
                        "write_allowed": _current_write_allowed(),
                        "error_type": exc.__class__.__name__,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_kind=write_kind, duration_ms=duration_ms, errored=False)

                result_type = type(result).__name__
                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "write_kind": write_kind,
                        "side_effects": side_effect.value,
                        "remote_write": bool(remote_write),
                        "write_allowed": _current_write_allowed(),
                        "result_type": result_type,
                        "user_message": _tool_user_message(
                            tool_name, write_action=ui_write_action, phase="ok", duration_ms=duration_ms
                        ),
                    }
                )

                TOOLS_LOGGER.detailed(
                    f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={result_type}",
                    extra={
                        "event": "tool_call_ok",
                        "status": "ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "write_kind": write_kind,
                        "side_effects": side_effect.value,
                        "remote_write": bool(remote_write),
                        "write_allowed": _current_write_allowed(),
                        "result_type": result_type,
                    },
                )
                return result

            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                title=tool_title,
                description=normalized_description,
                tags=tag_set,
                ui_write_action=ui_write_action,
                side_effect=side_effect,
                remote_write=remote_write,
                visibility=tool_visibility,
            )

            wrapper.__mcp_visibility__ = tool_visibility
            wrapper.__mcp_remote_write__ = remote_write
            wrapper.__mcp_write_action__ = ui_write_action  # UI prompt flag

            return wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            all_args = _bind_call_args(signature, args, kwargs)
            ctx = _extract_context(all_args)

            request_ctx = get_request_context()
            dedupe_key = _dedupe_key(tool_name, ui_write_action=ui_write_action, args_preview=ctx["arg_preview"])
            start = time.perf_counter()

            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_recent_start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                    "user_message": _tool_user_message(tool_name, write_action=ui_write_action, phase="start"),
                }
            )

            TOOLS_LOGGER.chat(
                _tool_user_message(tool_name, write_action=ui_write_action, phase="start"),
                extra={
                    "event": "tool_chat",
                    "status": "start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                },
            )

            TOOLS_LOGGER.detailed(
                f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                extra={
                    "event": "tool_call_start",
                    "status": "start",
                    "tool_name": tool_name,
                    "tags": sorted(tag_set),
                    "call_id": call_id,
                    "arg_keys": ctx["arg_keys"],
                    "arg_count": ctx["arg_count"],
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                },
            )

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_kind=write_kind, duration_ms=duration_ms, errored=True)

                structured_error = _structured_tool_error(exc, context=tool_name, path=None)
                error_info = structured_error.get("error", {}) if isinstance(structured_error, dict) else {}

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_error",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "error_type": exc.__class__.__name__,
                        "error_message": str(error_info.get("message") or exc.__class__.__name__),
                        "error_category": error_info.get("category"),
                        "error_origin": error_info.get("origin"),
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=ui_write_action,
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
                    }
                )

                TOOLS_LOGGER.detailed(
                    f"[tool error] tool={tool_name} | call_id={call_id}",
                    extra={
                        "event": "tool_call_error",
                        "status": "error",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "error_type": exc.__class__.__name__,
                    },
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _record_tool_call(tool_name, write_kind=write_kind, duration_ms=duration_ms, errored=False)

            result_type = type(result).__name__
            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_recent_ok",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                    "result_type": result_type,
                    "user_message": _tool_user_message(
                        tool_name, write_action=ui_write_action, phase="ok", duration_ms=duration_ms
                    ),
                }
            )

            TOOLS_LOGGER.detailed(
                f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={result_type}",
                extra={
                    "event": "tool_call_ok",
                    "status": "ok",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                    "result_type": result_type,
                },
            )
            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            title=tool_title,
            description=normalized_description,
            tags=tag_set,
            ui_write_action=ui_write_action,
            side_effect=side_effect,
            remote_write=remote_write,
            visibility=tool_visibility,
        )
        wrapper.__mcp_visibility__ = tool_visibility
        wrapper.__mcp_remote_write__ = remote_write
        wrapper.__mcp_write_action__ = ui_write_action  # UI prompt flag
        return wrapper

    return decorator


def register_extra_tools_if_available() -> None:
    """Register optional extra tools (if the optional module is present)."""
    try:
        from extra_tools import register_extra_tools  # type: ignore

        register_extra_tools(mcp_tool)
    except Exception:
        return None


def refresh_registered_tool_metadata(_write_allowed: object = None) -> None:
    """Refresh connector-facing metadata for registered tools."""
    effective_write_allowed = _current_write_allowed() if _write_allowed is None else bool(_write_allowed)

    for tool_obj, fn in list(_REGISTERED_MCP_TOOLS):
        try:
            tool_obj.meta["write_allowed"] = effective_write_allowed

            side_effect = getattr(fn, "__side_effect_class__", None)
            if not isinstance(side_effect, SideEffectClass):
                side_effect = resolve_side_effect_class(getattr(tool_obj, "name", "tool"))

            tool_obj.meta["ui_write_action"] = False
        except Exception:
            continue
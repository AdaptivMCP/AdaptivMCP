"""Decorators and helpers for registering MCP tools.

This module provides the `mcp_tool` decorator used across the repo.

Goals:
- Register tools with FastMCP while returning a callable function (so tools can
  call each other directly without dealing with FastMCP objects).
- Emit stable, testable log records for every tool call.
- Record a compact in-memory narrative of recent tool executions.

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
    _normalize_tool_description,
    _sanitize_metadata_value,
)
from github_mcp.metrics import _record_tool_call
from github_mcp.side_effects import (
    SideEffectClass,
    resolve_side_effect_class,
)

# Dedupe cache (best-effort, per-process).
_DEDUPE_TTL_SECONDS = 30.0
_DEDUPE_MAX_ENTRIES = 2048
_DEDUPE_INFLIGHT: dict[str, tuple[float, asyncio.Future[Any]]] = {}
_DEDUPE_RESULTS: dict[str, tuple[float, Any]] = {}
_DEDUPE_LOCK = asyncio.Lock()

def _ui_prompt_required_for_tool(
    tool_name: str,
    *,
    side_effect: SideEffectClass,
    write_allowed: bool,
) -> bool:
    """Whether the ChatGPT UI should prompt for approval before invoking the tool."""
    return False


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


def _log_tool_json_event(payload: Mapping[str, Any]) -> None:
    """Emit a machine-parseable record for tool lifecycle events.

    IMPORTANT: Do NOT embed raw JSON into the log message. Render's log viewer is
    human-centric, and embedding JSON inside the message (then appending
    `data=<json>` again) produces unreadable output full of escape sequences.

    Instead, we keep the message short and attach the structured payload via
    `extra`, which is appended once by the formatter.
    """
    try:
        base = dict(payload)

        safe = _sanitize_metadata_value(base)

        # Human-friendly, compact summary in message
        tool_name = str(payload.get('tool_name') or '')
        status = str(payload.get('status') or '')
        call_id = str(payload.get('call_id') or '')
        evt = str(payload.get('event') or 'tool_json')
        duration_ms = payload.get('duration_ms')
        dur = f" | duration_ms={duration_ms}" if isinstance(duration_ms, (int, float)) else ''
        msg = f"[tool event] {evt} | status={status} | tool={tool_name} | call_id={call_id}{dur}"

        TOOLS_LOGGER.detailed(
            msg,
            extra={
                'event': 'tool_json',
                'status': payload.get('status'),
                'tool_name': payload.get('tool_name'),
                'call_id': payload.get('call_id'),
                'tool_event': safe,
            },
        )
    except Exception:
        return

def _tool_user_message(
    tool_name: str,
    *,
    write_action: bool,
    phase: str,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> str:
    """Human console-style tool messages (Render logs are the primary debugger).

    Style goal: what you'd expect to see running commands locally.
    - Start:  → <tool> <arg_summary>
    - OK:     ← ok (<duration>)
    - Error:  ← error (<duration>) <reason>
"""
    scope = 'write' if write_action else 'read'
    dur = f" ({duration_ms}ms)" if duration_ms is not None else ''
    if phase == 'start':
        # Keep it terse; deeper details belong in structured payloads.
        return f"→ {tool_name} [{scope}]"
    if phase == 'ok':
        return f"← ok{dur}"
    if phase == 'error':
        suffix = f" {error}" if error else ''
        return f"← error{dur}{suffix}"
    return f"{tool_name} [{scope}]"

def _stable_request_id() -> Optional[str]:
    """Return a stable id for the current inbound request when available."""
    msg_id = REQUEST_MESSAGE_ID.get()
    if msg_id:
        return msg_id

    sess_id = REQUEST_SESSION_ID.get()
    if sess_id:
        return sess_id

    return None


def _dedupe_key(
    tool_name: str, *, ui_write_action: bool, args_preview: str
) -> Optional[str]:
    """Compute a dedupe key or return None when dedupe is disabled."""
    stable = _stable_request_id()
    if not stable:
        return None

    # For write actions that might be repeated intentionally, only dedupe when we have
    # an explicit per-message id so we don't suppress intentional repeated writes.
    if ui_write_action and not REQUEST_MESSAGE_ID.get():
        return None

    payload = {
        "id": stable,
        "tool": tool_name,
        "ui_write": bool(ui_write_action),
        "args": args_preview,
    }
    normalized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()


async def _maybe_dedupe_call(
    key: Optional[str], coro_factory: Callable[[], Any]
) -> Any:
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
            for k, _ in sorted(_DEDUPE_INFLIGHT.items(), key=lambda kv: kv[1][0])[
                : max(1, len(_DEDUPE_INFLIGHT) - _DEDUPE_MAX_ENTRIES)
            ]:
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
    read_only_hint = bool(side_effect is SideEffectClass.READ_ONLY and not remote_write)
    meta: dict[str, Any] = {
        "chatgpt.com/read_only_hint": read_only_hint,
    }

    annotations: dict[str, Any] = {}
    if read_only_hint:
        annotations["readOnlyHint"] = True
        annotations["read_only_hint"] = True

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

    wa = _current_write_allowed()
    tool_obj.meta["chatgpt.com/write_allowed"] = bool(wa)

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
        # Remote mutations should still be classified as REMOTE_MUTATION.
        remote_write = bool(write_action)
        side_effect = (
            SideEffectClass.REMOTE_MUTATION
            if remote_write
            else resolve_side_effect_class(tool_name)
        )
        # UI prompt behavior is disabled.
        initial_write_allowed = _current_write_allowed()
        ui_write_action = _ui_prompt_required_for_tool(
            tool_name, side_effect=side_effect, write_allowed=initial_write_allowed
        )

        write_kind = (
            "hard_write"
            if side_effect is SideEffectClass.REMOTE_MUTATION
            else "soft_write"
            if side_effect is SideEffectClass.LOCAL_MUTATION
            else "read_only"
        )

        llm_level = (
            "advanced" if side_effect is not SideEffectClass.READ_ONLY else "basic"
        )
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

                effective_write_allowed = _current_write_allowed()
                effective_ui_write_action = _ui_prompt_required_for_tool(
                    tool_name, side_effect=side_effect, write_allowed=effective_write_allowed
                )

                start = time.perf_counter()
                request_ctx = get_request_context()
                dedupe_key = _dedupe_key(
                    tool_name,
                    ui_write_action=effective_ui_write_action,
                    args_preview=ctx["arg_preview"],
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
                            tool_name, write_action=effective_ui_write_action, phase="start"
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name, write_action=effective_ui_write_action, phase="start"
                    ),
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

                _log_tool_json_event(
                    {
                        "event": "tool_call.start",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                        "dedupe_key": dedupe_key,
                        "write_kind": write_kind,
                        "side_effects": side_effect.value,
                        "remote_write": bool(remote_write),
                        "write_allowed": _current_write_allowed(),
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                    }
                )

                async def _run() -> Any:
                    return await func(*args, **kwargs)

                try:
                    result = await _maybe_dedupe_call(dedupe_key, _run)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name,
                        write_kind=write_kind,
                        duration_ms=duration_ms,
                        errored=True,
                    )

                    structured_error = _structured_tool_error(
                        exc, context=tool_name, path=None
                    )
                    error_info = (
                        structured_error.get("error", {})
                        if isinstance(structured_error, dict)
                        else {}
                    )

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
                            "ui_prompt_required": bool(effective_ui_write_action),
                            "error_type": exc.__class__.__name__,
                            "error_message": str(
                                error_info.get("message") or exc.__class__.__name__
                            ),
                            "error_category": error_info.get("category"),
                            "error_origin": error_info.get("origin"),
                            "user_message": _tool_user_message(
                                tool_name,
                                write_action=effective_ui_write_action,
                                phase="error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )

                    TOOLS_LOGGER.error(
                        _tool_user_message(
                            tool_name,
                            write_action=effective_ui_write_action,
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
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
                            "ui_prompt_required": bool(effective_ui_write_action),
                            "tool_error_type": exc.__class__.__name__,
                            "tool_error_message": str(error_info.get("message") or exc),
                            "tool_error_category": error_info.get("category"),
                            "tool_error_origin": error_info.get("origin"),
                            "tool_error_code": error_info.get("code"),
                            "tool_error_retryable": error_info.get("retryable"),
                        },
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
                            "ui_prompt_required": bool(effective_ui_write_action),
                            "tool_error_type": exc.__class__.__name__,
                            "tool_error_message": str(error_info.get("message") or exc),
                            "tool_error_category": error_info.get("category"),
                            "tool_error_origin": error_info.get("origin"),
                            "tool_error_code": error_info.get("code"),
                            "tool_error_retryable": error_info.get("retryable"),
                        },
                    )

                    _log_tool_json_event(
                        {
                            "event": "tool_call.error",
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
                            "ui_prompt_required": bool(effective_ui_write_action),
                            "error_type": exc.__class__.__name__,
                            "error_message": str(error_info.get("message") or exc),
                            "error_category": error_info.get("category"),
                            "error_origin": error_info.get("origin"),
                        }
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name,
                    write_kind=write_kind,
                    duration_ms=duration_ms,
                    errored=False,
                )

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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "result_type": result_type,
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=effective_ui_write_action,
                            phase="ok",
                            duration_ms=duration_ms,
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "result_type": result_type,
                    },
                )

                _log_tool_json_event(
                    {
                        "event": "tool_call.ok",
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "result_type": result_type,
                    }
                )

                return result

            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                title=None,
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

            effective_write_allowed = _current_write_allowed()
            effective_ui_write_action = _ui_prompt_required_for_tool(
                tool_name, side_effect=side_effect, write_allowed=effective_write_allowed
            )

            request_ctx = get_request_context()
            dedupe_key = _dedupe_key(
                tool_name,
                ui_write_action=effective_ui_write_action,
                args_preview=ctx["arg_preview"],
            )
            start = time.perf_counter()

            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_recent_start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                    "user_message": _tool_user_message(
                        tool_name, write_action=effective_ui_write_action, phase="start"
                    ),
                }
            )

            TOOLS_LOGGER.chat(
                _tool_user_message(
                    tool_name, write_action=effective_ui_write_action, phase="start"
                ),
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

            _log_tool_json_event(
                {
                    "event": "tool_call.start",
                    "status": "start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "dedupe_key": dedupe_key,
                    "write_kind": write_kind,
                    "side_effects": side_effect.value,
                    "remote_write": bool(remote_write),
                    "write_allowed": _current_write_allowed(),
                    "ui_prompt_required": bool(effective_ui_write_action),
                    "arg_keys": ctx["arg_keys"],
                    "arg_count": ctx["arg_count"],
                }
            )

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name,
                    write_kind=write_kind,
                    duration_ms=duration_ms,
                    errored=True,
                )

                structured_error = _structured_tool_error(
                    exc, context=tool_name, path=None
                )
                error_info = (
                    structured_error.get("error", {})
                    if isinstance(structured_error, dict)
                    else {}
                )

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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "error_type": exc.__class__.__name__,
                        "error_message": str(
                            error_info.get("message") or exc.__class__.__name__
                        ),
                        "error_category": error_info.get("category"),
                        "error_origin": error_info.get("origin"),
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=effective_ui_write_action,
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
                    }
                )

                TOOLS_LOGGER.error(
                    _tool_user_message(
                        tool_name,
                        write_action=effective_ui_write_action,
                        phase="error",
                        duration_ms=duration_ms,
                        error=f"{exc.__class__.__name__}: {exc}",
                    ),
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "tool_error_type": exc.__class__.__name__,
                        "tool_error_message": str(error_info.get("message") or exc),
                        "tool_error_category": error_info.get("category"),
                        "tool_error_origin": error_info.get("origin"),
                        "tool_error_code": error_info.get("code"),
                        "tool_error_retryable": error_info.get("retryable"),
                    },
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "tool_error_type": exc.__class__.__name__,
                        "tool_error_message": str(error_info.get("message") or exc),
                        "tool_error_category": error_info.get("category"),
                        "tool_error_origin": error_info.get("origin"),
                        "tool_error_code": error_info.get("code"),
                        "tool_error_retryable": error_info.get("retryable"),
                    },
                )

                _log_tool_json_event(
                    {
                        "event": "tool_call.error",
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                        "error_type": exc.__class__.__name__,
                        "error_message": str(error_info.get("message") or exc),
                        "error_category": error_info.get("category"),
                        "error_origin": error_info.get("origin"),
                    }
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _record_tool_call(
                tool_name, write_kind=write_kind, duration_ms=duration_ms, errored=False
            )

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
                    "ui_prompt_required": bool(effective_ui_write_action),
                    "result_type": result_type,
                    "user_message": _tool_user_message(
                        tool_name,
                        write_action=effective_ui_write_action,
                        phase="ok",
                        duration_ms=duration_ms,
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                    "result_type": result_type,
                },
            )

            _log_tool_json_event(
                {
                    "event": "tool_call.ok",
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
                        "ui_prompt_required": bool(effective_ui_write_action),
                    "result_type": result_type,
                }
            )

            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            title=None,
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
    effective_write_allowed = (
        _current_write_allowed() if _write_allowed is None else bool(_write_allowed)
    )

    for tool_obj, fn in list(_REGISTERED_MCP_TOOLS):
        try:
            tool_obj.meta["chatgpt.com/write_allowed"] = bool(effective_write_allowed)
        except Exception:
            continue

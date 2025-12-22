"""Decorators and helpers for registering MCP tools.

This module provides the `mcp_tool` decorator used across the repo.

Goals:
- Register tools with FastMCP while *returning a callable function* (so tools can
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
import json
import inspect
import time
import uuid
import sys
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.context import WRITE_ALLOWED, _record_recent_tool_event, mcp
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _sanitize_metadata_value,
    _title_from_tool_name,
)
from github_mcp.metrics import _record_tool_call
from github_mcp.redaction import redact_structured, redact_text
from github_mcp.side_effects import (
    SideEffectClass,
    compute_write_action_flag,
    resolve_side_effect_class,
)


# OpenAI connector UI strings.
# These appear in ChatGPT's Apps & Connectors UI while a tool is running.
# Keep them short and specific.
OPENAI_INVOKING_MESSAGE = "Adaptiv Controller: running tool…"
OPENAI_INVOKED_MESSAGE = "Adaptiv Controller: tool finished."


def _current_write_allowed() -> bool:
    try:
        import github_mcp.server as server_mod

        return bool(getattr(server_mod, "WRITE_ALLOWED", WRITE_ALLOWED))
    except Exception:
        return bool(WRITE_ALLOWED)


def _bind_call_args(signature: Optional[inspect.Signature], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Dict[str, Any]:
    if signature is None:
        return dict(kwargs)
    try:
        bound = signature.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return dict(kwargs)


def _extract_context(all_args: Mapping[str, Any]) -> dict[str, Any]:
    repo = None
    if isinstance(all_args.get("full_name"), str):
        repo = all_args["full_name"]
    elif isinstance(all_args.get("owner"), str) and isinstance(all_args.get("repo"), str):
        repo = f"{all_args['owner']}/{all_args['repo']}"

    ref = None
    for key in ("ref", "branch", "base_ref", "head_ref"):
        val = all_args.get(key)
        if isinstance(val, str):
            ref = val
            break

    path = None
    for key in ("path", "file_path"):
        val = all_args.get(key)
        if isinstance(val, str):
            path = val
            break

    arg_keys = sorted([k for k in all_args.keys()])
    arg_preview = redact_text(_format_tool_args_preview(all_args))

    return {
        "repo": repo,
        "ref": ref,
        "path": path,
        "arg_keys": arg_keys,
        "arg_count": len(all_args),
        "arg_preview": arg_preview,
    }


def _tool_user_message(
    tool_name: str,
    *,
    write_action: bool,
    repo: Optional[str],
    ref: Optional[str],
    path: Optional[str],
    phase: str,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> str:
    scope = "write" if write_action else "read"

    location = repo or "-"
    if ref:
        location = f"{location}@{ref}"
    if path:
        location = f"{location}:{path}"

    if phase == "start":
        msg = f"Starting {tool_name} ({scope}) on {location}."
        if write_action:
            msg += " This will modify repo state."
        return msg

    if phase == "ok":
        dur = f" in {duration_ms}ms" if duration_ms is not None else ""
        return f"Finished {tool_name} on {location}{dur}."

    if phase == "error":
        dur = f" after {duration_ms}ms" if duration_ms is not None else ""
        suffix = f" ({error})" if error else ""
        return f"Failed {tool_name} on {location}{dur}.{suffix}"

    return f"{tool_name} ({scope}) on {location}."


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    title: Optional[str],
    description: Optional[str],
    tags: set[str],
    write_action: bool,
    side_effect: SideEffectClass,
    visibility: str = "public",
) -> Any:
    # FastMCP supports `meta` and `annotations`; tests and UI rely on these.
    meta: dict[str, Any] = {
        "write_action": bool(write_action),
        "visibility": visibility,
        "side_effects": side_effect.value,
    }

    for domain_prefix in ("openai", "chatgpt.com"):
        # Connector UI metadata (Apps & Connectors). These keys are intentionally
        # flat (not nested) because the UI historically reads them directly from
        # `meta`.
        meta[f"{domain_prefix}/visibility"] = visibility
        meta[f"{domain_prefix}/toolInvocation/invoking"] = OPENAI_INVOKING_MESSAGE
        meta[f"{domain_prefix}/toolInvocation/invoked"] = OPENAI_INVOKED_MESSAGE
        meta[f"{domain_prefix}/side_effects"] = side_effect.value
    if title:
        # Helpful for UIs that support a distinct display label.
        meta["title"] = title
        for domain_prefix in ("openai", "chatgpt.com"):
            meta[f"{domain_prefix}/title"] = title
    annotations = {
        "readOnlyHint": bool(side_effect is SideEffectClass.READ_ONLY),
        "title": title or _title_from_tool_name(name),
    }

    tool_obj = mcp.tool(
        fn,
        name=name,
        description=description,
        tags=tags,
        meta=meta,
        annotations=annotations,
    )

    # Keep registry stable: replace existing entry with the same name.
    _REGISTERED_MCP_TOOLS[:] = [
        (t, f)
        for (t, f) in _REGISTERED_MCP_TOOLS
        if (getattr(t, "name", None) or getattr(f, "__name__", None)) != name
    ]
    _REGISTERED_MCP_TOOLS.append((tool_obj, fn))

    # Replace generic visibility labels with a schema-derived identifier so the
    # connector UI displays the active schema rather than a static value like "public".
    # Format: schema:<tool_name>:<sha1-10>
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

        tool_obj.meta["visibility"] = schema_visibility
        for domain_prefix in ("openai", "chatgpt.com"):
            tool_obj.meta[f"{domain_prefix}/visibility"] = schema_visibility

    except Exception:
        # Never fail tool registration over UI metadata.
        pass
    finally:
        # Always surface machine-readable schemas and the active write gate state
        # to ChatGPT so connectors don't block safe operations.
        sanitized_schema = sanitized_schema or _sanitize_metadata_value(
            schema or {"type": "object", "properties": {}}
        )

        tool_obj.meta["schema"] = sanitized_schema
        tool_obj.meta["input_schema"] = sanitized_schema
        tool_obj.meta["write_allowed"] = _current_write_allowed()

        for domain_prefix in ("openai", "chatgpt.com"):
            tool_obj.meta[f"{domain_prefix}/schema"] = sanitized_schema
            tool_obj.meta[f"{domain_prefix}/input_schema"] = sanitized_schema
            tool_obj.meta[f"{domain_prefix}/write_allowed"] = _current_write_allowed()

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
    """Decorator used across the repo to register an MCP tool.

    Returns a function wrapper (not the FastMCP tool object) to preserve
    intra-module calls.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")

        tool_visibility = _ignored.get("visibility", visibility)
        tool_title = _title_from_tool_name(tool_name)

        side_effect = resolve_side_effect_class(tool_name)

        def _write_action_flag() -> bool:
            return compute_write_action_flag(side_effect, write_allowed=_current_write_allowed())

        llm_level = "advanced" if side_effect is not SideEffectClass.READ_ONLY else "basic"
        normalized_description = description or _normalize_tool_description(func, signature, llm_level=llm_level)

        tag_set = set(tags or [])
        tag_set.add("write" if side_effect is not SideEffectClass.READ_ONLY else "read")

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)
                ctx = _extract_context(all_args)
                write_action = _write_action_flag()

                start = time.perf_counter()

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="start",
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="start",
                    ),
                    extra={
                        "event": "tool_chat",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                    extra={
                        "event": "tool_call_start",
                        "status": "start",
                        "tool_name": tool_name,
                        "write_action": write_action,
                        "tags": sorted(tag_set),
                        "call_id": call_id,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                    },
                )

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)

                    _record_tool_call(tool_name, write_action=write_action, duration_ms=duration_ms, errored=True)
                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                            "user_message": _tool_user_message(
                                tool_name,
                                write_action=write_action,
                                repo=ctx["repo"],
                                ref=ctx["ref"],
                                path=ctx["path"],
                                phase="error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )

                    TOOLS_LOGGER.chat(
                        _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
                        extra={
                            "event": "tool_chat",
                            "status": "error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                        },
                    )

                    TOOLS_LOGGER.exception(
                        f"[tool error] tool={tool_name} | call_id={call_id}",
                        extra={
                            "event": "tool_call_error",
                            "status": "error",
                            "tool_name": tool_name,
                            "write_action": write_action,
                            "tags": sorted(tag_set),
                            "call_id": call_id,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "arg_keys": ctx["arg_keys"],
                            "arg_count": ctx["arg_count"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_action=write_action, duration_ms=duration_ms, errored=False)
                result_type = type(result).__name__

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "duration_ms": duration_ms,
                        "result_type": result_type,
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="ok",
                            duration_ms=duration_ms,
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="ok",
                        duration_ms=duration_ms,
                    ),
                    extra={
                        "event": "tool_chat",
                        "status": "ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "duration_ms": duration_ms,
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={result_type}",
                    extra={
                        "event": "tool_call_success",
                        "status": "ok",
                        "tool_name": tool_name,
                        "write_action": write_action,
                        "tags": sorted(tag_set),
                        "call_id": call_id,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                        "duration_ms": duration_ms,
                        "result_type": result_type,
                    },
                )

                return result

        else:

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)
                ctx = _extract_context(all_args)
                write_action = _write_action_flag()

                start = time.perf_counter()

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="start",
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="start",
                    ),
                    extra={
                        "event": "tool_chat",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                    extra={
                        "event": "tool_call_start",
                        "status": "start",
                        "tool_name": tool_name,
                        "write_action": write_action,
                        "tags": sorted(tag_set),
                        "call_id": call_id,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                    },
                )

                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)

                    _record_tool_call(tool_name, write_action=write_action, duration_ms=duration_ms, errored=True)

                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                            "user_message": _tool_user_message(
                                tool_name,
                                write_action=write_action,
                                repo=ctx["repo"],
                                ref=ctx["ref"],
                                path=ctx["path"],
                                phase="error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )

                    TOOLS_LOGGER.chat(
                        _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
                        extra={
                            "event": "tool_chat",
                            "status": "error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                        },
                    )

                    TOOLS_LOGGER.exception(
                        f"[tool error] tool={tool_name} | call_id={call_id}",
                        extra={
                            "event": "tool_call_error",
                            "status": "error",
                            "tool_name": tool_name,
                            "write_action": write_action,
                            "tags": sorted(tag_set),
                            "call_id": call_id,
                            "repo": ctx["repo"],
                            "ref": ctx["ref"],
                            "path": ctx["path"],
                            "arg_keys": ctx["arg_keys"],
                            "arg_count": ctx["arg_count"],
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(tool_name, write_action=write_action, duration_ms=duration_ms, errored=False)
                result_type = type(result).__name__

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "duration_ms": duration_ms,
                        "result_type": result_type,
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="ok",
                            duration_ms=duration_ms,
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="ok",
                        duration_ms=duration_ms,
                    ),
                    extra={
                        "event": "tool_chat",
                        "status": "ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "duration_ms": duration_ms,
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={result_type}",
                    extra={
                        "event": "tool_call_success",
                        "status": "ok",
                        "tool_name": tool_name,
                        "write_action": write_action,
                        "tags": sorted(tag_set),
                        "call_id": call_id,
                        "repo": ctx["repo"],
                        "ref": ctx["ref"],
                        "path": ctx["path"],
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                        "duration_ms": duration_ms,
                        "result_type": result_type,
                    },
                )

                return result

        invoking_msg = f"Adaptiv: {tool_title}"
        invoked_msg = f"Adaptiv: {tool_title} done"
        setattr(
            wrapper,
            "__openai__",
            {
                "invoking_message": invoking_msg,
                "invoked_message": invoked_msg,
            },
        )

        # Ensure connector UI gets the normalized description.
        try:
            wrapper.__doc__ = normalized_description
        except Exception:
            pass

        _register_with_fastmcp(
            wrapper,
            name=tool_name,
            title=tool_title,
            description=normalized_description,
            tags=tag_set,
            write_action=_write_action_flag(),
            side_effect=side_effect,
            visibility=tool_visibility,
        )

        return wrapper

    return decorator


def refresh_registered_tool_metadata(write_allowed: Optional[bool] = None) -> None:
    """Refresh tool metadata when the global write gate changes."""

    allowed = _current_write_allowed() if write_allowed is None else bool(write_allowed)
    try:
        import github_mcp.server as server_mod

        server_mod.WRITE_ALLOWED = allowed
        server_mod._WRITE_ALLOWED_INITIALIZED = True
    except Exception:
        pass
    for tool_obj, func in list(_REGISTERED_MCP_TOOLS):
        try:
            tool_name = getattr(tool_obj, "name", None) or getattr(func, "__name__", "")
            side_effect = getattr(tool_obj, "__side_effect_class__", None) or resolve_side_effect_class(
                tool_name
            )
            write_flag = compute_write_action_flag(side_effect, write_allowed=allowed)
        except Exception:
            continue

        try:
            tool_obj.meta["write_action"] = write_flag
            tool_obj.meta["write_allowed"] = allowed
            tool_obj.meta["side_effects"] = side_effect.value
            for domain_prefix in ("openai", "chatgpt.com"):
                tool_obj.meta[f"{domain_prefix}/write_allowed"] = allowed
                tool_obj.meta[f"{domain_prefix}/side_effects"] = side_effect.value
        except Exception:
            # Metadata refresh should never break tool execution.
            continue


def register_extra_tools_if_available() -> None:
    """Best-effort import of optional `extra_tools` module."""

    try:
        extra_tools = __import__("extra_tools")
    except ImportError:
        return

    try:
        register = getattr(extra_tools, "register_extra_tools", None)
        if callable(register):
            register(mcp_tool)
    except Exception:
        TOOLS_LOGGER.error("register_extra_tools failed", exc_info=True)

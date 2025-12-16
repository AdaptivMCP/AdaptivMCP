"""Decorators and helpers for registering MCP tools.

This module provides the `mcp_tool` decorator used across the repo to:
- declare tools + schemas
- normalize common arguments
- emit consistent logs/events for observability
- attach OpenAI connector UI metadata
"""

from __future__ import annotations

import asyncio
import functools as _functools
import inspect
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from pydantic import BaseModel

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.errors import ToolInputValidationError

# OpenAI connector UI strings.
# These appear in ChatGPT's Apps & Connectors UI while a tool is running.
# Keep them short, scannable, and specific to this project.
OPENAI_INVOKING_MESSAGE = "Adaptiv Controller: running tool…"
OPENAI_INVOKED_MESSAGE = "Adaptiv Controller: tool finished."

# This list records recent tool events that the server exposes for diagnostics.
# The host UI may not stream per-step updates (especially on mobile), so these
# events are also useful for tools like get_recent_tool_events.
RECENT_TOOL_EVENTS_CAPACITY = 200
_RECENT_TOOL_EVENTS: deque[dict[str, Any]] = deque(maxlen=RECENT_TOOL_EVENTS_CAPACITY)


def _record_recent_tool_event(event: dict[str, Any]) -> None:
    _RECENT_TOOL_EVENTS.append(event)


def get_recent_tool_events(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), RECENT_TOOL_EVENTS_CAPACITY))
    return list(_RECENT_TOOL_EVENTS)[-limit:]


def _format_args_for_log(args: Mapping[str, Any], *, max_len: int = 220) -> str:
    """Format a safe preview of tool args for logs.

    Avoid dumping large blobs (file content, base64, etc.) into provider logs.
    """

    parts: list[str] = []
    for k, v in args.items():
        if k in {"updated_content", "content", "patch", "diff", "body"}:
            if isinstance(v, str):
                parts.append(f"{k}=<str:{len(v)}>")
            elif isinstance(v, (bytes, bytearray)):
                parts.append(f"{k}=<bytes:{len(v)}>")
            else:
                parts.append(f"{k}=<blob>")
            continue

        if isinstance(v, str):
            vv = v
            if len(vv) > 80:
                vv = vv[:77] + "…"
            parts.append(f"{k}={vv!r}")
        else:
            parts.append(f"{k}={type(v).__name__}")

    preview = ", ".join(parts)
    if len(preview) > max_len:
        preview = preview[: max_len - 1] + "…"
    return preview


@dataclass
class Tool:
    name: str
    func: Callable[..., Any]
    write_action: bool
    tags: set[str]
    input_schema: dict[str, Any]


TOOLS: Dict[str, Tool] = {}


def _build_input_schema(func: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    props: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name.startswith("_"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        schema: dict[str, Any] = {}
        ann = param.annotation
        if ann in (int, Optional[int]):
            schema["type"] = "integer"
        elif ann in (float, Optional[float]):
            schema["type"] = "number"
        elif ann in (bool, Optional[bool]):
            schema["type"] = "boolean"
        elif ann in (dict, Dict[str, Any], Optional[Dict[str, Any]]):
            schema["type"] = "object"
        elif ann in (list, Sequence[str], Optional[Sequence[str]]):
            schema["type"] = "array"
            schema["items"] = {"type": "string"}
        else:
            schema["type"] = "string"

        # Basic help text from docstrings isn't available here; descriptions are
        # handled in the MCP tool list.
        props[name] = schema
        if param.default is inspect._empty:
            required.append(name)

    out: dict[str, Any] = {
        "type": "object",
        "properties": props,
    }
    if required:
        out["required"] = required
    return out


def _preflight_tool_args(tool: Tool, provided_args: Mapping[str, Any]) -> None:
    # Minimal schema validation to fail fast and surface better errors.
    schema = tool.input_schema
    required = schema.get("required") or []
    for req in required:
        if req not in provided_args:
            raise ToolInputValidationError(
                tool_name=tool.name,
                message=f"Missing required argument: {req}",
                field=req,
            )


def mcp_tool(*, write_action: bool, tags: Optional[Iterable[str]] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool = Tool(
            name=func.__name__,
            func=func,
            write_action=write_action,
            tags=set(tags or []),
            input_schema=_build_input_schema(func),
        )
        TOOLS[tool.name] = tool

        signature = None
        try:
            signature = inspect.signature(func)
        except Exception:
            signature = None

        has_var_kw = False
        if signature is not None:
            for param in signature.parameters.values():
                if param.kind == inspect.Parameter.VAR_KEYWORD:
                    has_var_kw = True
                    break

        def _normalize_common_tool_kwargs(args, kwargs):
            # Normalize common aliases used by the assistant.
            if signature is None:
                return kwargs

            params = signature.parameters
            provided_positional = set(list(params)[: len(args)])

            # owner+repo -> full_name
            if (
                "full_name" in params
                and "full_name" not in kwargs
                and "full_name" not in provided_positional
                and isinstance(kwargs.get("owner"), str)
                and isinstance(kwargs.get("repo"), str)
            ):
                kwargs["full_name"] = f"{kwargs['owner']}/{kwargs['repo']}"

            # branch -> ref
            if (
                "ref" in params
                and "ref" not in kwargs
                and "ref" not in provided_positional
                and isinstance(kwargs.get("branch"), str)
            ):
                kwargs["ref"] = kwargs["branch"]

            # base -> base_branch (PR tools)
            if (
                "base_branch" in params
                and "base_branch" not in kwargs
                and "base_branch" not in provided_positional
                and isinstance(kwargs.get("base"), str)
            ):
                kwargs["base_branch"] = kwargs["base"]

            # head -> new_branch (PR tools)
            if (
                "new_branch" in params
                and "new_branch" not in kwargs
                and "new_branch" not in provided_positional
                and isinstance(kwargs.get("head"), str)
            ):
                kwargs["new_branch"] = kwargs["head"]

            # branch -> base_branch (PR tools)
            if (
                "base_branch" in params
                and "base_branch" not in kwargs
                and "base_branch" not in provided_positional
                and isinstance(kwargs.get("branch"), str)
            ):
                kwargs["base_branch"] = kwargs["branch"]

            # file_path -> path
            if (
                "path" in params
                and "path" not in kwargs
                and "path" not in provided_positional
                and isinstance(kwargs.get("file_path"), str)
            ):
                kwargs["path"] = kwargs["file_path"]

            # file_paths -> paths
            if (
                "paths" in params
                and "paths" not in kwargs
                and "paths" not in provided_positional
                and isinstance(kwargs.get("file_paths"), list)
            ):
                fps = kwargs.get("file_paths")
                if isinstance(fps, list) and all(isinstance(x, str) for x in fps):
                    kwargs["paths"] = fps

            # Normalize nested file entries for update_files_and_open_pr
            if tool.name == "update_files_and_open_pr" and isinstance(kwargs.get("files"), list):
                for entry in kwargs["files"]:
                    if not isinstance(entry, dict):
                        continue
                    if "path" not in entry and isinstance(entry.get("file_path"), str):
                        entry["path"] = entry.pop("file_path")
                    if "content" not in entry and isinstance(entry.get("updated_content"), str):
                        entry["content"] = entry.pop("updated_content")

            # Drop unknown keys unless tool accepts **kwargs
            if not has_var_kw:
                for key in list(kwargs.keys()):
                    if key not in params:
                        kwargs.pop(key, None)
            return kwargs

        def _extract_call_context(args, **kwargs):
            all_args: Dict[str, Any] = {}

            if signature is not None:
                try:
                    bound = signature.bind_partial(*args, **kwargs)
                    all_args = dict(bound.arguments)
                except Exception:
                    all_args = {}

            if not all_args:
                all_args = dict(kwargs)

            repo_full_name: Optional[str] = None
            if isinstance(all_args.get("full_name"), str):
                repo_full_name = all_args["full_name"]
            elif isinstance(all_args.get("owner"), str) and isinstance(all_args.get("repo"), str):
                repo_full_name = f"{all_args['owner']}/{all_args['repo']}"

            ref: Optional[str] = None
            for key in ("ref", "branch", "base_ref", "head_ref"):
                value = all_args.get(key)
                if isinstance(value, str):
                    ref = value
                    break

            path: Optional[str] = None
            for key in ("path", "file_path"):
                value = all_args.get(key)
                if isinstance(value, str):
                    path = value
                    break

            arg_keys = sorted(set(all_args.keys()))
            arg_preview = _format_args_for_log(all_args)
            return {
                "repo": repo_full_name,
                "ref": ref,
                "path": path,
                "arg_keys": arg_keys,
                "arg_count": len(all_args),
                "arg_preview": arg_preview,
                "_all_args": all_args,
            }

        def _result_size_hint(result: Any) -> Optional[int]:
            if isinstance(result, (list, tuple, str)):
                return len(result)
            if isinstance(result, dict):
                return len(result)
            return None

        def _human_context(call_id: str, context: Mapping[str, Any]) -> str:
            scope = "write" if write_action else "read"
            repo = context["repo"] or "-"
            ref = context["ref"] or "-"
            path = context["path"] or "-"
            arg_preview = context.get("arg_preview") or "<no args>"
            return (
                f"tool={tool.name} ({scope}) | call_id={call_id} | repo={repo} | "
                f"ref={ref} | path={path} | args={arg_preview}"
            )

        if asyncio.iscoroutinefunction(func):
            @_functools.wraps(func)
            async def wrapper(*args, **kwargs):
                kwargs = _normalize_common_tool_kwargs(args, kwargs)
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)

                def _tool_user_message(
                    phase: str,
                    *,
                    duration_ms: int | None = None,
                    error: str | None = None,
                ) -> str:
                    repo = context.get("repo") or "-"
                    ref = context.get("ref") or "-"
                    path = context.get("path") or "-"
                    scope = "write" if write_action else "read"

                    location = repo
                    if ref and ref != "-":
                        location = f"{location}@{ref}"
                    if path and path not in {"-", ""}:
                        location = f"{location}:{path}"

                    if phase == "start":
                        prefix = f"Starting {tool.name} ({scope}) on {location}."
                        if write_action:
                            return prefix + " This will modify repo state."
                        return prefix
                    if phase == "ok":
                        dur = f" in {duration_ms}ms" if duration_ms is not None else ""
                        return f"Finished {tool.name} on {location}{dur}."
                    if phase == "error":
                        dur = f" after {duration_ms}ms" if duration_ms is not None else ""
                        msg = f" ({error})" if error else ""
                        return f"Failed {tool.name} on {location}{dur}.{msg}"
                    return f"{tool.name} ({scope}) on {location}."

                start = time.perf_counter()

                _preflight_tool_args(tool, context.get("_all_args", {}))
                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_start",
                        "tool_name": tool.name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": context.get("repo"),
                        "ref": context.get("ref"),
                        "path": context.get("path"),
                        "user_message": _tool_user_message("start"),
                    }
                )

                TOOLS_LOGGER.info(
                    f"[tool start] {_human_context(call_id, context)}",
                    extra={
                        "event": "tool_call_start",
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tool.tags) if tool.tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "arg_count": context["arg_count"],
                        "arg_preview": context["arg_preview"],
                    },
                )

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_error",
                            "tool_name": tool.name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "repo": context.get("repo"),
                            "ref": context.get("ref"),
                            "path": context.get("path"),
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                            "user_message": _tool_user_message(
                                "error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )
                    TOOLS_LOGGER.exception(
                        f"[tool error] {_human_context(call_id, context)}",
                        extra={
                            "event": "tool_call_error",
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "call_id": call_id,
                            "repo": context.get("repo"),
                            "ref": context.get("ref"),
                            "path": context.get("path"),
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool.name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "repo": context.get("repo"),
                        "ref": context.get("ref"),
                        "path": context.get("path"),
                        "duration_ms": duration_ms,
                        "result_size_hint": _result_size_hint(result),
                        "user_message": _tool_user_message("ok", duration_ms=duration_ms),
                    }
                )
                TOOLS_LOGGER.info(
                    f"[tool ok] {_human_context(call_id, context)} | duration_ms={duration_ms}",
                    extra={
                        "event": "tool_call_ok",
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "call_id": call_id,
                        "repo": context.get("repo"),
                        "ref": context.get("ref"),
                        "path": context.get("path"),
                        "duration_ms": duration_ms,
                    },
                )
                return result

            # Attach OpenAI UI metadata used by the connector.
            setattr(wrapper, "__openai__", {
                "invoking_message": OPENAI_INVOKING_MESSAGE,
                "invoked_message": OPENAI_INVOKED_MESSAGE,
            })
            setattr(wrapper, "__mcp_tool__", tool)
            return wrapper

        # sync function
        @_functools.wraps(func)
        def wrapper(*args, **kwargs):
            kwargs = _normalize_common_tool_kwargs(args, kwargs)
            _preflight_tool_args(tool, kwargs)
            return func(*args, **kwargs)

        setattr(wrapper, "__openai__", {
            "invoking_message": OPENAI_INVOKING_MESSAGE,
            "invoked_message": OPENAI_INVOKED_MESSAGE,
        })
        setattr(wrapper, "__mcp_tool__", tool)
        return wrapper

    return decorator

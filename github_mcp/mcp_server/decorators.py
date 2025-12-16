from __future__ import annotations

import asyncio

import time
import uuid
from typing import Any, Dict, Mapping, Optional

from mcp.types import ToolAnnotations

from github_mcp.config import BASE_LOGGER, TOOLS_LOGGER
from github_mcp.metrics import _record_tool_call

from github_mcp.mcp_server.context import CONTROLLER_REPO, mcp, _record_recent_tool_event
from github_mcp.mcp_server.errors import _summarize_exception
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_tool_description,
    _preflight_tool_args,
    _title_from_tool_name,
)

def mcp_tool(*, write_action: bool = False, **tool_kwargs):
    existing_tags = tool_kwargs.pop("tags", None)
    tags: set[str] = set(existing_tags or [])
    if write_action:
        tags.add("write")
    else:
        tags.add("read")

    llm_level = "advanced" if write_action else "low-level"
    tags.add(llm_level)

    existing_meta = tool_kwargs.pop("meta", None) or {}
    existing_annotations = tool_kwargs.pop("annotations", None)

    annotations: ToolAnnotations | None
    if isinstance(existing_annotations, ToolAnnotations):
        annotations = existing_annotations
    elif isinstance(existing_annotations, dict):
        annotations = ToolAnnotations(**existing_annotations)
    else:
        annotations = None

    if annotations is None:
        annotations = ToolAnnotations(readOnlyHint=not write_action)
    elif annotations.readOnlyHint is None:
        annotations = annotations.model_copy(update={"readOnlyHint": not write_action})
    if not isinstance(existing_meta, dict):
        existing_meta = {}
    risk_level = "high" if write_action else "low"
    operation = "write" if write_action else "read"
    meta = {
        **existing_meta,
        "write_action": write_action,
        "auto_approved": not write_action,
        "risk_level": risk_level,
        "operation": operation,
        "llm_level": llm_level,
        "llm_guidance": "This tool description is expanded for ChatGPT and includes explicit inputs and risk level.",
        "openai/visibility": existing_meta.get("openai/visibility") or existing_meta.get("visibility") or "public",
    }

    import functools as _functools
    import inspect as _inspect

    def decorator(func):
        nonlocal annotations
        signature = None
        try:
            signature = _inspect.signature(func)
        except (TypeError, ValueError):
            signature = None

        normalized_description = _normalize_tool_description(func, signature, llm_level=llm_level)
        tool_kwargs.setdefault("description", normalized_description)
        tool_kwargs.setdefault("title", _title_from_tool_name(func.__name__))
        meta.setdefault("openai/toolInvocation/invoking", "Running…")
        meta.setdefault("openai/toolInvocation/invoked", "Completed")
        func.__doc__ = normalized_description

        # Provide a human-readable title for clients that render tool lists.
        if getattr(annotations, "title", None) is None:
            annotations = annotations.model_copy(update={"title": _title_from_tool_name(func.__name__)})

        final_annotations = annotations
        if getattr(final_annotations, "title", None) is None:
            final_annotations = final_annotations.model_copy(
                update={"title": _title_from_tool_name(func.__name__)}
            )

        tool = mcp.tool(
            tags=tags or None,
            meta=meta or None,
            annotations=final_annotations,
            **tool_kwargs,
        )(func)

        def _format_args_for_log(all_args: Mapping[str, Any], *, limit: int = 1200) -> str:
            return _format_tool_args_preview(all_args, limit=limit)

        def _normalize_common_tool_kwargs(args_in, kwargs_in: Mapping[str, Any]) -> Dict[str, Any]:
            if not kwargs_in:
                kwargs: Dict[str, Any] = {}
                return kwargs
            kwargs = dict(kwargs_in)
            if signature is None:
                return kwargs
            params = signature.parameters
            has_var_kw = any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in params.values())

            # Which params are already provided positionally?
            positional = [
                name
                for name, p in params.items()
                if p.kind
                in (_inspect.Parameter.POSITIONAL_ONLY, _inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            provided_positional = set(positional[: len(args_in)])

            # owner/repo -> full_name (and default full_name if omitted)
            if (
                "full_name" in params
                and "full_name" not in kwargs
                and "full_name" not in provided_positional
            ):
                owner = kwargs.get("owner")
                repo = kwargs.get("repo")
                repo_val = repo if isinstance(repo, str) else None
                # Common mistake: pass full "owner/repo" under key "repo".
                if repo_val and "/" in repo_val and not isinstance(owner, str):
                    kwargs["full_name"] = repo_val
                elif isinstance(owner, str) and isinstance(repo, str):
                    kwargs["full_name"] = f"{owner}/{repo}"
                else:
                    kwargs["full_name"] = CONTROLLER_REPO

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
                def _tool_user_message(phase: str, *, duration_ms: int | None = None, error: str | None = None) -> str:
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

                # Preflight validation of arguments against the tool's declared
                # input schema, similar to validate_tool_args but applied
                # automatically for every call.
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
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "arg_count": context["arg_count"],
                        "arg_preview": context["arg_preview"],
                    },
                )

                errored = False
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_exception",
                            "tool_name": tool.name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "message": _summarize_exception(exc)[:200],
                            "repo": context.get("repo"),
                            "ref": context.get("ref"),
                        "path": context.get("path"),
                            "user_message": _tool_user_message("error", duration_ms=duration_ms, error=_summarize_exception(exc)[:120]),
                        }
                    )
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        f"[tool error] {_human_context(call_id, context)} | duration_ms={duration_ms} | "
                        f"error={exc.__class__.__name__}: {exc}",
                        extra={
                            "event": "tool_call_error",
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
                            "arg_count": context["arg_count"],
                            "arg_preview": context["arg_preview"],
                            "duration_ms": duration_ms,
                            "status": "error",
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name=tool.name,
                    write_action=write_action,
                    duration_ms=duration_ms,
                    errored=errored,
                )
                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool.name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "duration_ms": duration_ms,
                        "repo": context.get("repo"),
                        "ref": context.get("ref"),
                        "result_type": type(result).__name__,
                        "user_message": _tool_user_message("ok", duration_ms=duration_ms),
                    }
                )
                TOOLS_LOGGER.info(
                    f"[tool ok] {_human_context(call_id, context)} | duration_ms={duration_ms} | "
                    f"result_type={type(result).__name__} | result_size_hint={_result_size_hint(result)}",
                    extra={
                        "event": "tool_call_success",
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "arg_count": context["arg_count"],
                        "arg_preview": context["arg_preview"],
                        "duration_ms": duration_ms,
                        "status": "ok",
                        "result_type": type(result).__name__,
                        "result_size_hint": _result_size_hint(result),
                    },
                )
                return result

        else:

            @_functools.wraps(func)
            def wrapper(*args, **kwargs):
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)
                def _tool_user_message(phase: str, *, duration_ms: int | None = None, error: str | None = None) -> str:
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

                # Preflight validation of arguments against the tool's declared
                # input schema, similar to validate_tool_args but applied
                # automatically for every call.
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
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "arg_count": context["arg_count"],
                        "arg_preview": context["arg_preview"],
                    },
                )

                errored = False
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_exception",
                            "tool_name": tool.name,
                            "call_id": call_id,
                            "write_action": write_action,
                            "duration_ms": duration_ms,
                            "error_type": exc.__class__.__name__,
                            "message": _summarize_exception(exc)[:200],
                            "repo": context.get("repo"),
                            "ref": context.get("ref"),
                            "path": context.get("path"),
                            "user_message": _tool_user_message(
                                "error",
                                duration_ms=duration_ms,
                                error=_summarize_exception(exc)[:120],
                            ),
                        }
                    )
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        f"[tool error] {_human_context(call_id, context)} | duration_ms={duration_ms} | "
                        f"error={exc.__class__.__name__}: {exc}",
                        extra={
                            "event": "tool_call_error",
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
                            "arg_count": context["arg_count"],
                            "arg_preview": context["arg_preview"],
                            "duration_ms": duration_ms,
                            "status": "error",
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name=tool.name,
                    write_action=write_action,
                    duration_ms=duration_ms,
                    errored=errored,
                )
                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool.name,
                        "call_id": call_id,
                        "write_action": write_action,
                        "duration_ms": duration_ms,
                        "repo": context.get("repo"),
                        "ref": context.get("ref"),
                        "result_type": type(result).__name__,
                        "user_message": _tool_user_message("ok", duration_ms=duration_ms),
                    }
                )
                TOOLS_LOGGER.info(
                    f"[tool ok] {_human_context(call_id, context)} | duration_ms={duration_ms} | "
                    f"result_type={type(result).__name__} | result_size_hint={_result_size_hint(result)}",
                    extra={
                        "event": "tool_call_success",
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "arg_count": context["arg_count"],
                        "arg_preview": context["arg_preview"],
                        "duration_ms": duration_ms,
                        "status": "ok",
                        "result_type": type(result).__name__,
                        "result_size_hint": _result_size_hint(result),
                    },
                )
                return result

        wrapper._mcp_tool = tool  # type: ignore[attr-defined]
        _REGISTERED_MCP_TOOLS.append((tool, wrapper))
        return wrapper

    return decorator

def register_extra_tools_if_available():
    try:
        from extra_tools import register_extra_tools  # type: ignore[import]
    except Exception:
        register_extra_tools = None  # type: ignore[assignment]

    if callable(register_extra_tools):
        BASE_LOGGER.info("registering additional MCP tools from extra_tools.py")
        try:
            register_extra_tools(mcp_tool)
        except Exception:
            BASE_LOGGER.exception("register_extra_tools failed")

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
import inspect
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from github_mcp.config import TOOLS_LOGGER
from github_mcp.mcp_server.context import _record_recent_tool_event, mcp
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_tool_description,
    _title_from_tool_name,
)
from github_mcp.metrics import _record_tool_call

# OpenAI connector UI strings.
# These appear in ChatGPT's Apps & Connectors UI while a tool is running.
# Keep them short and specific.
OPENAI_INVOKING_MESSAGE = "Adaptiv Controller: running tool…"
OPENAI_INVOKED_MESSAGE = "Adaptiv Controller: tool finished."


def _bind_call_args(
    signature: Optional[inspect.Signature], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Dict[str, Any]:
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
    arg_preview = _format_tool_args_preview(all_args)

    return {
        "repo": repo,
        "ref": ref,
        "path": path,
        "arg_keys": arg_keys,
        "arg_count": len(all_args),
        "arg_preview": arg_preview,
    }


def _summarize_command(command: str) -> str:
    cmd = " ".join(command.strip().split())
    if len(cmd) > 160:
        cmd = cmd[:157] + "…"
    return cmd


def _tool_narrative(tool_name: str, all_args: Mapping[str, Any] | None) -> dict[str, str]:
    """Return user-facing purpose/next-step strings for a tool invocation.

    These messages are intended to be readable in provider logs (Render) and in the
    controller's in-memory transcript. They must not include internal correlation
    IDs or secrets.
    """

    all_args = all_args or {}

    purpose = "Capturing context so the next step is clear."
    next_step = "Review the output and decide what to do next."

    if tool_name in {"search_workspace", "search"}:
        q = all_args.get("query")
        p = all_args.get("path")
        if isinstance(q, str) and q.strip():
            where = f" in {p}" if isinstance(p, str) and p.strip() else ""
            purpose = (
                f"Searching the codebase{where} to locate relevant definitions and references."
            )
        else:
            purpose = "Searching the codebase to locate relevant definitions and references."
        next_step = "Open the most relevant matches and inspect the surrounding code."

    elif tool_name in {
        "get_file_with_line_numbers",
        "get_file_slice",
        "get_file_contents",
        "get_workspace_file_contents",
        "open_file_context",
        "fetch_files",
        "get_cached_files",
        "cache_files",
    }:
        p = all_args.get("path") or all_args.get("workspace_path") or all_args.get("target_path")
        if isinstance(p, str) and p.strip():
            purpose = f"Reading {p} to inspect source and validate behavior."
        else:
            purpose = "Reading file contents to inspect source and validate behavior."
        next_step = "Review the contents and decide whether a change is needed."

    elif tool_name in {
        "terminal_command",
        "run_command",
        "run_tests",
        "run_lint_suite",
        "run_quality_suite",
    }:
        cmd = (
            all_args.get("command") or all_args.get("test_command") or all_args.get("lint_command")
        )
        cmd_s = _summarize_command(cmd) if isinstance(cmd, str) else ""
        if "pytest" in cmd_s or "python -m pytest" in cmd_s:
            purpose = "Running the test suite to validate behavior and prevent regressions."
            next_step = "Address any failures and re-run tests."
        elif "ruff" in cmd_s or "flake8" in cmd_s or "mypy" in cmd_s:
            purpose = "Running linters/static checks to keep code quality and consistency."
            next_step = "Fix any lint/type errors and re-run checks."
        else:
            purpose = "Running a terminal command to gather diagnostics or validate changes."
            next_step = "Review the output and act on any warnings/errors."

    elif "render" in tool_name and "log" in tool_name:
        purpose = "Fetching provider logs to verify runtime behavior and troubleshoot issues."
        next_step = "Scan for errors/warnings and correlate them with recent tool activity."

    elif "commit" in tool_name or tool_name in {"update_file_from_workspace"}:
        purpose = "Saving changes to the repository so CI and deployment can run."
        next_step = "Verify CI passes and confirm the deployment behaves as expected."

    return {"purpose": purpose, "next_step": next_step}


def _tool_user_message(
    tool_name: str,
    *,
    tool_title: str | None = None,
    all_args: Mapping[str, Any] | None = None,
    write_action: bool,
    repo: Optional[str],
    ref: Optional[str],
    path: Optional[str],
    phase: str,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> str:
    scope = "write" if write_action else "read"

    title = tool_title or _title_from_tool_name(tool_name)

    # Only include a target when we have something meaningful.
    location = None
    if repo or ref or path:
        location = repo or "-"
        if ref:
            location = f"{location}@{ref}"
        if path:
            location = f"{location}:{path}"

    narrative = _tool_narrative(tool_name, all_args)
    purpose = narrative["purpose"]
    next_step = narrative["next_step"]

    loc = f" on {location}" if location and location != "-" else ""

    if phase == "start":
        msg = f"Starting {title} ({scope}){loc}. {purpose}"
        if write_action:
            msg += " This will modify repo state."
        return msg

    if phase == "ok":
        dur = f" in {duration_ms}ms" if duration_ms is not None else ""
        return f"Finished {title}{loc}{dur}. Next: {next_step}"

    if phase == "error":
        dur = f" after {duration_ms}ms" if duration_ms is not None else ""
        suffix = f" Error: {error}." if error else ""
        return f"Failed {title}{loc}{dur}.{suffix} Next: {next_step}"

    return f"{title} ({scope}){loc}."


def _tool_detailed_message(
    tool_name: str,
    *,
    tool_title: str | None,
    all_args: Mapping[str, Any] | None,
    write_action: bool,
    repo: Optional[str],
    ref: Optional[str],
    path: Optional[str],
    phase: str,
    arg_preview: str,
    duration_ms: Optional[int] = None,
    result_type: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    scope = "write" if write_action else "read"
    title = tool_title or _title_from_tool_name(tool_name)

    target = None
    if repo or ref or path:
        target = repo or "-"
        if ref:
            target = f"{target}@{ref}"
        if path:
            target = f"{target}:{path}"

    narrative = _tool_narrative(tool_name, all_args)
    purpose = narrative["purpose"]
    next_step = narrative["next_step"]

    parts: list[str] = [
        f"Tool={title}",
        f"scope={scope}",
    ]
    if target and target != "-":
        parts.append(f"target={target}")

    if phase == "start":
        parts.append(f"inputs={arg_preview}")
        parts.append(f"purpose={purpose}")
        parts.append(f"next={next_step}")
        return " | ".join(parts)

    if phase == "ok":
        if duration_ms is not None:
            parts.append(f"duration_ms={duration_ms}")
        if result_type:
            parts.append(f"result_type={result_type}")
        parts.append(f"next={next_step}")
        return " | ".join(parts)

    if phase == "error":
        if duration_ms is not None:
            parts.append(f"duration_ms={duration_ms}")
        if error:
            parts.append(f"error={error}")
        parts.append(f"inputs={arg_preview}")
        parts.append(f"next={next_step}")
        return " | ".join(parts)

    parts.append(f"phase={phase}")
    return " | ".join(parts)


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    title: Optional[str],
    description: Optional[str],
    tags: set[str],
    write_action: bool,
    visibility: str = "public",
) -> Any:
    # FastMCP supports `meta` and `annotations`; tests and UI rely on these.
    meta: dict[str, Any] = {
        "write_action": bool(write_action),
        "auto_approved": bool(not write_action),
        "visibility": visibility,
        # OpenAI connector UI metadata (Apps & Connectors).
        #
        # These keys are intentionally flat (not nested) because OpenAI's connector
        # UI historically reads them from `meta` directly.
        "openai/visibility": visibility,
        "openai/toolInvocation/invoking": OPENAI_INVOKING_MESSAGE,
        "openai/toolInvocation/invoked": OPENAI_INVOKED_MESSAGE,
    }
    if title:
        # Helpful for UIs that support a distinct display label.
        meta["title"] = title
        meta["openai/title"] = title
    annotations = {
        "readOnlyHint": bool(not write_action),
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

        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(
            func, signature, llm_level=llm_level
        )

        tag_set = set(tags or [])
        tag_set.add("write" if write_action else "read")

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)
                ctx = _extract_context(all_args)

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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        tool_title=tool_title,
                        all_args=all_args,
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
                    _tool_detailed_message(
                        tool_name,
                        tool_title=tool_title,
                        all_args=all_args,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="start",
                        arg_preview=ctx["arg_preview"],
                    ),
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

                    _record_tool_call(
                        tool_name, write_action=write_action, duration_ms=duration_ms, errored=True
                    )
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
                                tool_title=tool_title,
                                all_args=all_args,
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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        _tool_detailed_message(
                            tool_name,
                            tool_title=tool_title,
                            all_args=all_args,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="error",
                            arg_preview=ctx["arg_preview"],
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
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
                _record_tool_call(
                    tool_name, write_action=write_action, duration_ms=duration_ms, errored=False
                )
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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        tool_title=tool_title,
                        all_args=all_args,
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
                    _tool_detailed_message(
                        tool_name,
                        tool_title=tool_title,
                        all_args=all_args,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="ok",
                        arg_preview=ctx["arg_preview"],
                        duration_ms=duration_ms,
                        result_type=result_type,
                    ),
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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        tool_title=tool_title,
                        all_args=all_args,
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
                    _tool_detailed_message(
                        tool_name,
                        tool_title=tool_title,
                        all_args=all_args,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="start",
                        arg_preview=ctx["arg_preview"],
                    ),
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

                    _record_tool_call(
                        tool_name, write_action=write_action, duration_ms=duration_ms, errored=True
                    )

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
                                tool_title=tool_title,
                                all_args=all_args,
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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        _tool_detailed_message(
                            tool_name,
                            tool_title=tool_title,
                            all_args=all_args,
                            write_action=write_action,
                            repo=ctx["repo"],
                            ref=ctx["ref"],
                            path=ctx["path"],
                            phase="error",
                            arg_preview=ctx["arg_preview"],
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
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
                _record_tool_call(
                    tool_name, write_action=write_action, duration_ms=duration_ms, errored=False
                )
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
                            tool_title=tool_title,
                            all_args=all_args,
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
                        tool_title=tool_title,
                        all_args=all_args,
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
                    _tool_detailed_message(
                        tool_name,
                        tool_title=tool_title,
                        all_args=all_args,
                        write_action=write_action,
                        repo=ctx["repo"],
                        ref=ctx["ref"],
                        path=ctx["path"],
                        phase="ok",
                        arg_preview=ctx["arg_preview"],
                        duration_ms=duration_ms,
                        result_type=result_type,
                    ),
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
            write_action=write_action,
            visibility=tool_visibility,
        )

        return wrapper

    return decorator


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

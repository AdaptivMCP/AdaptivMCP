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


def _tool_phase_label(
    tool_name: str, *, write_action: bool, all_args: Mapping[str, Any] | None
) -> str:
    """Classify tool activity into user-facing operating phases.

    Assistants should follow the phases:
      - Discovery
      - Implementation
      - Testing/Verification
      - Commit/Push

    This helper makes those phases visible in Render logs without requiring users
    to understand tool names.
    """

    name = (tool_name or "").lower()

    if name in {"run_tests", "run_lint_suite", "run_quality_suite"}:
        return "Testing/Verification"

    if "render" in name and ("log" in name or "metric" in name):
        return "Verification"

    if (
        name.startswith("commit")
        or "pull_request" in name
        or name
        in {
            "create_pull_request",
            "open_pr_for_existing_branch",
            "update_files_and_open_pr",
            "apply_text_update_and_commit",
            "update_file_from_workspace",
        }
    ):
        return "Commit/Push"

    if write_action:
        return "Implementation"

    return "Discovery"


def _clip(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def _tool_result_summary(tool_name: str, result: Any) -> str:
    """Summarize tool results for user-facing logs.

    Avoid leaking internal IDs or dumping huge payloads. Detailed logs may include
    short excerpts for high-signal tools like terminal_command.
    """

    name = (tool_name or "").lower()

    # Common structured error shape.
    if isinstance(result, dict) and "error" in result and result.get("error"):
        err = str(result.get("error"))
        details = result.get("details")
        if isinstance(details, dict) and details.get("exit_code") is not None:
            return f"error={_clip(err, max_chars=120)}, exit_code={details.get('exit_code')}"
        return f"error={_clip(err, max_chars=160)}"

    # Terminal/shell results.
    if isinstance(result, dict) and (
        "exit_code" in result or "stdout" in result or "stderr" in result
    ):
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out")) if "timed_out" in result else None
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        so_tr = bool(result.get("stdout_truncated")) if "stdout_truncated" in result else False
        se_tr = bool(result.get("stderr_truncated")) if "stderr_truncated" in result else False

        parts = []
        if exit_code is not None:
            parts.append(f"exit_code={exit_code}")
        if timed_out is not None:
            parts.append(f"timed_out={timed_out}")

        def _count_lines(s: str) -> int:
            return 0 if not s else (s.count("\n") + (0 if s.endswith("\n") else 1))

        if stdout:
            parts.append(f"stdout={_count_lines(stdout)} lines")
        if stderr:
            parts.append(f"stderr={_count_lines(stderr)} lines")
        if so_tr:
            parts.append("stdout_truncated=True")
        if se_tr:
            parts.append("stderr_truncated=True")

        summary = ", ".join(parts) if parts else "completed"

        # For terminal-like tools, include a short excerpt in detailed logs.
        if name in {"terminal_command", "run_tests", "run_lint_suite", "run_quality_suite"}:
            excerpt_lines = 18

            out_excerpt = ""
            if stdout.strip():
                lines = stdout.splitlines()[:excerpt_lines]
                out_excerpt = "\n".join(lines)
                if so_tr or len(stdout.splitlines()) > excerpt_lines:
                    out_excerpt += "\n…(stdout truncated)…"

            err_excerpt = ""
            if stderr.strip():
                lines = stderr.splitlines()[:excerpt_lines]
                err_excerpt = "\n".join(lines)
                if se_tr or len(stderr.splitlines()) > excerpt_lines:
                    err_excerpt += "\n…(stderr truncated)…"

            blocks: list[str] = []
            if out_excerpt:
                blocks.append("stdout:\n" + out_excerpt)
            if err_excerpt:
                blocks.append("stderr:\n" + err_excerpt)

            if blocks:
                return summary + "\n" + "\n".join(blocks)

        return summary

    # Lists/collections.
    if isinstance(result, list):
        return f"items={len(result)}"

    if isinstance(result, str):
        return f"text={len(result)} chars"

    if result is None:
        return "no result"

    # Generic fallback.
    return f"type={type(result).__name__}"


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
    result_summary: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    scope = "write" if write_action else "read"

    phase_label = _tool_phase_label(tool_name, write_action=write_action, all_args=all_args)

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
        msg = f"{phase_label} — I'm going to {title} ({scope}){loc}. {purpose}"
        if write_action:
            msg += " This will modify repo state."
        return msg

    if phase == "ok":
        dur = f" in {duration_ms}ms" if duration_ms is not None else ""
        rs = (result_summary or "").strip()
        rs = _clip(rs, max_chars=160) if rs else ""
        extra = f" Result: {rs}." if rs else ""
        return f"{phase_label} — Done: {title}{loc}{dur}.{extra} Next: {next_step}"

    if phase == "error":
        dur = f" after {duration_ms}ms" if duration_ms is not None else ""
        suffix = f" Error: {error}." if error else ""
        return f"{phase_label} — I hit an error while running {title}{loc}{dur}.{suffix} Next: {next_step}"

    return f"{title} ({scope}){loc}."


def _tool_inputs_summary(tool_name: str, all_args: Mapping[str, Any] | None) -> str:
    """Summarize user-relevant inputs without dumping raw stats/IDs.

    This intentionally omits null/empty fields and internal correlation IDs.
    """

    all_args = dict(all_args or {})

    # Remove internal/noise keys if present.
    for k in [
        "call_id",
        "ownerId",
        "owner_id",
        "resource",
        "clientIP",
        "client_ip",
        "requestID",
        "request_id",
        "args",
    ]:
        all_args.pop(k, None)

    def pick(*keys: str):
        for k in keys:
            v = all_args.get(k)
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            return v
        return None

    def fmt_kv(k: str, v: object) -> str:
        if isinstance(v, str):
            s = " ".join(v.strip().split())
            if len(s) > 180:
                s = s[:177] + "…"
            return f"{k}={s!r}"
        return f"{k}={v!r}"

    # Tool-specific summaries.
    if tool_name in {"search_workspace", "search"}:
        q = pick("query", "q")
        path = pick("path")
        parts = []
        if q is not None:
            parts.append(fmt_kv("query", q))
        if path is not None:
            parts.append(fmt_kv("path", path))
        return ", ".join(parts) if parts else "No inputs."

    if tool_name in {"get_file_with_line_numbers", "get_file_slice", "get_file_contents"}:
        path = pick("path")
        start = pick("start_line", "start")
        max_lines = pick("max_lines")
        parts = []
        if path is not None:
            parts.append(fmt_kv("file", path))
        if start is not None:
            parts.append(fmt_kv("start_line", start))
        if max_lines is not None:
            parts.append(fmt_kv("max_lines", max_lines))
        return ", ".join(parts) if parts else "No inputs."

    if tool_name in {"terminal_command", "run_command"}:
        cmd = pick("command")
        timeout = pick("timeout_seconds")
        use_temp = pick("use_temp_venv")
        installing = pick("installing_dependencies")
        parts = []
        if cmd is not None:
            parts.append(fmt_kv("command", cmd))
        if timeout is not None:
            parts.append(fmt_kv("timeout_seconds", timeout))
        if use_temp is True:
            parts.append("temp_venv=True")
        if installing is True:
            parts.append("install_deps=True")
        return ", ".join(parts) if parts else "No inputs."

    if "render" in tool_name and "log" in tool_name:
        direction = pick("direction")
        limit = pick("limit")
        level = pick("level", "min_level")
        text_filter = pick("text")
        parts = []
        if level is not None:
            parts.append(fmt_kv("level", level))
        if text_filter is not None:
            parts.append(fmt_kv("filter", text_filter))
        if direction is not None:
            parts.append(fmt_kv("direction", direction))
        if limit is not None:
            parts.append(fmt_kv("limit", limit))
        return ", ".join(parts) if parts else "No inputs."

    if tool_name in {"apply_text_update_and_commit", "update_file_from_workspace"}:
        path = pick("path")
        message = pick("commit_message", "message")
        parts = []
        if path is not None:
            parts.append(fmt_kv("file", path))
        if message is not None:
            parts.append(fmt_kv("message", message))
        return ", ".join(parts) if parts else "No inputs."

    # Generic fallback: include a small, cleaned set of keys.
    cleaned: list[str] = []
    for k in sorted(all_args.keys()):
        v = all_args.get(k)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, dict)) and not v:
            continue
        if k in {"repo", "ref", "path", "full_name"}:
            continue
        cleaned.append(fmt_kv(k, v))
        if len(cleaned) >= 6:
            break

    return ", ".join(cleaned) if cleaned else "No inputs."


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
    result_summary: Optional[str] = None,
    result_type: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    """User-facing detailed log message.

    Detailed logs should read like a professional progress narrative, not a dump of
    internal stats/correlation IDs.
    """

    scope = "write" if write_action else "read"
    title = tool_title or _title_from_tool_name(tool_name)

    phase_label = _tool_phase_label(tool_name, write_action=write_action, all_args=all_args)

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
    inputs = _tool_inputs_summary(tool_name, all_args)

    if phase == "start":
        msg = f"Details — {phase_label} — Starting {title} ({scope}){loc}. {purpose}"
        if inputs and inputs != "No inputs.":
            msg += f" Inputs: {inputs}."
        if write_action:
            msg += " This will modify repo state."
        msg += f" Next: {next_step}"
        return msg

    if phase == "ok":
        dur = f" Completed in {duration_ms}ms." if duration_ms is not None else ""
        rs = (result_summary or "").strip()
        rs = _clip(rs, max_chars=1200) if rs else ""
        out = f" Result: {rs}." if rs else (f" Output: {result_type}." if result_type else "")
        return f"Details — {phase_label} — Finished {title}{loc}.{dur}{out} Next: {next_step}"

    if phase == "error":
        dur = f" After {duration_ms}ms." if duration_ms is not None else ""
        err = f" Error: {error}." if error else ""
        msg = f"Details — {phase_label} — Failed {title}{loc}.{dur}{err}"
        if inputs and inputs != "No inputs.":
            msg += f" Inputs: {inputs}."
        msg += f" Next: {next_step}"
        return msg

    return f"Details — {title} ({scope}){loc}."


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
                        result_summary=_tool_result_summary(tool_name, result),
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
                        result_summary=_tool_result_summary(tool_name, result),
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
                        result_summary=_tool_result_summary(tool_name, result),
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
                        result_summary=_tool_result_summary(tool_name, result),
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

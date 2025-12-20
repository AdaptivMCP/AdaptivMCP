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
import github_mcp.server as server
from github_mcp.mcp_server.context import _record_recent_tool_event, mcp
from github_mcp.mcp_server.errors import ToolInputValidationError
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _title_from_tool_name,
)
from github_mcp.metrics import _record_tool_call
from github_mcp.mcp_server.privacy import strip_location_metadata
from github_mcp.redaction import redact_sensitive_text

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
    arg_keys = sorted([k for k in all_args.keys()])
    arg_preview = _format_tool_args_preview(all_args)

    return {
        # Repo/ref/path tracking intentionally disabled to avoid leaking location data.
        "repo": None,
        "ref": None,
        "path": None,
        "arg_keys": arg_keys,
        "arg_count": len(all_args),
        "arg_preview": arg_preview,
    }


def _summarize_command(command: str) -> str:
    cmd = " ".join(command.strip().split())
    if len(cmd) > 160:
        cmd = cmd[:157] + "…"
    return cmd


def _tool_inputs_summary(tool_name: str, all_args: Mapping[str, Any] | None) -> str:
    """Return a human-readable summary of tool inputs for detailed logs.

    This should be safe to show to users (no secrets) and compact.
    """

    if not all_args:
        return "No inputs."

    # Redact obvious secret-bearing keys.
    redact_keys = {
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "authorization",
        "cookie",
        "service_id",
        "owner_id",
    }

    safe_args: dict[str, Any] = {}
    for k, v in dict(all_args).items():
        lk = str(k).lower()
        if lk in redact_keys or any(t in lk for t in ("key", "secret", "token", "password")):
            safe_args[str(k)] = "<redacted>"
        else:
            safe_args[str(k)] = redact_sensitive_text(str(v)) if isinstance(v, str) else v

    # Tool-specific hints.
    cmd = safe_args.get("command")
    if isinstance(cmd, str):
        return redact_sensitive_text(f"command={_summarize_command(cmd)}")

    url = safe_args.get("url")
    if isinstance(url, str):
        return redact_sensitive_text(f"url={_clip(url, max_chars=220)}")

    # Default: compact JSON-ish preview produced by schemas helper.
    return redact_sensitive_text(_format_tool_args_preview(safe_args))


def _tool_phase_label(
    tool_name: str, *, write_action: bool = False, all_args: Mapping[str, Any] | None
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


def _openai_is_consequential(
    tool_name: str,
    tags: Iterable[str] | None,
    *,
    write_action: bool = False,
    ui_consequential: bool | None = None,
) -> bool:
    """Classify tools for connector UI gating (Apps & Connectors)."""

    if ui_consequential is not None:
        return bool(ui_consequential)

    auto_approve_on = bool(getattr(server, "AUTO_APPROVE_ENABLED", False))

    name = (tool_name or "").lower()
    tag_set = {str(t).lower() for t in (tags or [])}

    if name.startswith("workspace_"):
        # Workspace helpers are intentionally ungated so setup flows remain fast.
        return False

    if name in {"web_fetch", "web_search"} or "web" in tag_set:
        return True

    if name == "render_cli_command" or "render-cli" in tag_set:
        # Render CLI should only be gated when auto-approve is disabled; when
        # WRITE_ALLOWED is on, treat it as non-consequential so the connector
        # does not block actions/tool calls behind the write gate.
        return not server.WRITE_ALLOWED

    if write_action:
        # Auto-approve bypasses most prompts, but write-tagged tools still need
        # to prompt when auto-approve is disabled.
        return not auto_approve_on

    if "push" in name or any(t in {"push", "git-push", "git_push"} or "push" in t for t in tag_set):
        return True

    return False


def _clip(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


# ------------------------------------------------------------------------------
# Transport-safe tool results

_CONTROL_CHAR_TABLE = {i: None for i in range(0, 32) if chr(i) not in ("\n", "\t")}


def _sanitize_text(s: str, *, max_chars: int) -> str:
    # Normalize and drop control characters that can confuse clients/log viewers.
    s = (s or "").replace("\r", "")
    try:
        s = s.translate(_CONTROL_CHAR_TABLE)
    except Exception:
        pass
    return _clip(s, max_chars=max_chars)


def _sanitize_tool_result(
    obj: Any,
    *,
    max_depth: int = 6,
    max_list_items: int = 200,
    max_dict_items: int = 200,
    max_string_chars: int = 60000,
    total_char_budget: int = 120000,
) -> Any:
    """Best-effort sanitize/truncate tool results for transport.

    This defends against huge payloads, control characters, and non-JSONable objects
    that can cause connector/network disconnects.
    """

    budget = [int(total_char_budget)]

    def _needs_sanitization(x: Any, depth: int) -> bool:
        """Return True if we must sanitize/copy to keep transport safe."""

        if depth > max_depth:
            return True

        if x is None or isinstance(x, (bool, int, float)):
            return False

        if isinstance(x, (bytes, bytearray, memoryview)):
            return True

        if isinstance(x, str):
            if x != x.replace("\r", ""):
                return True
            try:
                if x.translate(_CONTROL_CHAR_TABLE) != x:
                    return True
            except Exception:
                return True
            if len(x) > max_string_chars:
                return True
            return False

        if isinstance(x, dict):
            if len(x) > max_dict_items:
                return True
            for k, v in x.items():
                if not isinstance(k, str):
                    return True
                if _needs_sanitization(k, depth + 1):
                    return True
                if _needs_sanitization(v, depth + 1):
                    return True
            return False

        if isinstance(x, list):
            if len(x) > max_list_items:
                return True
            for v in x:
                if _needs_sanitization(v, depth + 1):
                    return True
            return False

        return True

    # Fast path: preserve identity for already-safe JSON-shaped results.
    try:
        if isinstance(obj, (dict, list, str)) and not _needs_sanitization(obj, 0):
            return obj
    except Exception:
        pass

    def walk(x: Any, depth: int) -> Any:
        if budget[0] <= 0:
            return "…(truncated)…"
        if depth > max_depth:
            s = _sanitize_text(str(x), max_chars=min(max_string_chars, budget[0]))
            budget[0] -= len(s)
            return s

        if x is None or isinstance(x, (bool, int, float)):
            return x

        if isinstance(x, bytes):
            try:
                x = x.decode("utf-8", errors="replace")
            except Exception:
                x = str(x)

        if isinstance(x, str):
            s = _sanitize_text(x, max_chars=min(max_string_chars, budget[0]))
            budget[0] -= len(s)
            return s

        if isinstance(x, dict):
            out: dict[str, Any] = {}
            items = list(x.items())
            for k, v in items[:max_dict_items]:
                ks = _sanitize_text(str(k), max_chars=256)
                out[ks] = walk(v, depth + 1)
                if budget[0] <= 0:
                    break
            if len(items) > max_dict_items:
                out["…"] = f"…({len(items) - max_dict_items} more keys)…"
            return out

        if isinstance(x, (list, tuple, set)):
            seq = list(x)
            out_list = [walk(v, depth + 1) for v in seq[:max_list_items]]
            if len(seq) > max_list_items:
                out_list.append(f"…({len(seq) - max_list_items} more items)…")
            return out_list

        s = _sanitize_text(str(x), max_chars=min(max_string_chars, budget[0]))
        budget[0] -= len(s)
        return s

    return walk(obj, 0)


def _tool_result_summary(tool_name: str, result: Any, *, verbosity: str = "detailed") -> str:
    """Summarize tool results for user-facing logs.

    - CHAT logs should be short and conversational.
    - DETAILED logs can include small, high-signal excerpts (terminal output, diffs).

    Avoid leaking internal IDs or dumping huge payloads.
    """

    def _first_line(s: str, *, max_chars: int = 180) -> str:
        s = (s or "").strip().replace("\r", "")
        if not s:
            return ""
        line = s.splitlines()[0]
        return _clip(line, max_chars=max_chars)

    def _pipe_prefix(block: str, *, prefix: str = "│ ") -> str:
        # Keep multi-line blocks readable even if the log viewer splits on newlines.
        parts = (block or "").replace("\r", "").splitlines() or [""]
        return "\n".join(prefix + ln for ln in parts)

    # Many workspace tools return wrapper shapes like:
    #   {"repo_dir": ..., "result": {"exit_code":..., "stdout":..., ...}}
    # Unwrap nested shell results so summaries are meaningful.
    if isinstance(result, dict):
        inner = result.get("result")
        if isinstance(inner, dict) and (
            "exit_code" in inner
            or "stdout" in inner
            or "stderr" in inner
            or ("error" in inner and inner.get("error"))
        ):
            return _tool_result_summary(tool_name, inner, verbosity=verbosity)

        # Common read-tool shapes.
        if isinstance(result.get("lines"), list):
            start_line = result.get("start_line")
            end_line = result.get("end_line")
            n = len(result.get("lines") or [])
            if isinstance(start_line, int) and isinstance(end_line, int):
                return f"read lines {start_line}-{end_line} ({n} lines)"
            return f"read {n} lines"

        if isinstance(result.get("results"), list):
            return f"found {len(result.get('results') or [])} matches"

        if isinstance(result.get("logs"), list):
            return f"fetched {len(result.get('logs') or [])} log lines"

        # Unified diffs from commit/update tools.
        diff = result.get("diff") or result.get("unified_diff")
        if isinstance(diff, str) and diff.strip():
            if verbosity == "chat":
                return "generated a patch (see detailed logs for the diff)"
            diff_lines = diff.splitlines()
            max_lines = 140
            clipped = "\n".join(diff_lines[:max_lines])
            if len(diff_lines) > max_lines:
                clipped += "\n…(diff truncated)…"
            return "diff:\n" + _pipe_prefix(clipped)

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
        timed_out = bool(result.get("timed_out")) if "timed_out" in result else False
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        so_tr = bool(result.get("stdout_truncated")) if "stdout_truncated" in result else False
        se_tr = bool(result.get("stderr_truncated")) if "stderr_truncated" in result else False

        if verbosity == "chat":
            parts: list[str] = []
            if timed_out:
                parts.append("timed out")
            r1 = _first_line(stdout)
            e1 = _first_line(stderr)
            if r1:
                parts.append(f"Response: {r1}")
            if e1:
                label = "Diagnostics" if exit_code in (None, 0) else "Errors"
                parts.append(f"{label}: {e1}")
            return " | ".join(parts) if parts else "completed"

        def _excerpt(label: str, s: str, *, truncated: bool) -> str:
            if not s.strip():
                return ""
            excerpt_lines = 18
            raw_lines = s.replace("\r", "").splitlines()
            view = raw_lines[:excerpt_lines]
            out = "\n".join(view)
            if truncated or len(raw_lines) > excerpt_lines:
                out += f"\n…({label} truncated)…"
            return f"{label}:\n" + _pipe_prefix(out)

        blocks: list[str] = []
        if timed_out:
            blocks.append("Timed out while waiting for the command to finish.")

        response_block = _excerpt("Response", stdout, truncated=so_tr)
        diag_label = "Diagnostics" if exit_code in (None, 0) else "Errors"
        diagnostics_block = _excerpt(diag_label, stderr, truncated=se_tr)

        if response_block:
            blocks.append(response_block)
        if diagnostics_block:
            blocks.append(diagnostics_block)

        if not blocks:
            return "completed"

        return "\n".join(blocks)

    # Lists/collections.
    if isinstance(result, list):
        return f"items={len(result)}"

    if isinstance(result, str):
        if verbosity == "chat":
            return (
                _clip(result.strip().replace("\r", "").replace("\n", " "), max_chars=160) or "text"
            )
        return f"text={len(result)} chars"

    if result is None:
        return "no result"

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
    write_action: bool = False,
    repo: str | None = None,
    ref: str | None = None,
    path: str | None = None,
    phase: str = "start",
    duration_ms: int | None = None,
    result_summary: str | None = None,
    error: str | None = None,
) -> str:
    """User-facing chat log message.

    This intentionally reads like an assistant speaking to a human.
    Avoid internal IDs/stats; focus on *what* is happening and *what comes next*.

    Backwards-compatible with older call-sites that pass (tool_title, all_args, phase...).
    """

    phase_label = _tool_phase_label(tool_name, write_action=write_action, all_args=all_args)
    title = tool_title or _title_from_tool_name(tool_name)

    narrative = _tool_narrative(tool_name, all_args)
    purpose = narrative["purpose"]
    next_step = narrative["next_step"]

    status = phase

    if status == "start":
        return f"{phase_label} — Starting {title}. {purpose} Next: {next_step}"

    if status == "ok":
        summary = (result_summary or "").strip() or "done"
        dur = f" ({duration_ms}ms)" if duration_ms is not None else ""
        return f"{phase_label} — Finished {title}{dur}. {summary}. Next: {next_step}"

    err = (error or "unknown error").strip()
    dur = f" ({duration_ms}ms)" if duration_ms is not None else ""
    return f"{phase_label} — {title} failed{dur}: {_clip(err, max_chars=200)}. Next: {next_step}"


def _tool_detailed_message(
    tool_name: str,
    *,
    tool_title: str | None,
    all_args: Mapping[str, Any] | None,
    write_action: bool = False,
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

    title = tool_title or _title_from_tool_name(tool_name)

    phase_label = _tool_phase_label(tool_name, write_action=write_action, all_args=all_args)

    narrative = _tool_narrative(tool_name, all_args)
    purpose = narrative["purpose"]
    next_step = narrative["next_step"]

    inputs = _tool_inputs_summary(tool_name, all_args)

    if phase == "start":
        msg = f"Details — {phase_label} — Starting {title}. {purpose}"
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
        return f"Details — {phase_label} — Finished {title}.{dur}{out} Next: {next_step}"

    if phase == "error":
        dur = f" After {duration_ms}ms." if duration_ms is not None else ""
        err = f" Error: {error}." if error else ""
        msg = f"Details — {phase_label} — Failed {title}.{dur}{err}"
        if inputs and inputs != "No inputs.":
            msg += f" Inputs: {inputs}."
        msg += f" Next: {next_step}"
        return msg

    return f"Details — {title}."


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    title: Optional[str],
    description: Optional[str],
    tags: set[str],
    write_action: bool = False,
    openai_is_consequential: bool,
    visibility: str = "public",
    openai_invoking_message: Optional[str] = None,
    openai_invoked_message: Optional[str] = None,
) -> Any:
    compact_metadata = bool(getattr(server, "COMPACT_METADATA_DEFAULT", False))

    # The controller manifest should present all actions as non-consequential
    # and read-only so connector clients treat them as safe without additional
    # prompts. Keep the incoming ``openai_is_consequential`` parameter for
    # compatibility but force the surfaced metadata to reflect the stricter
    # contract here.
    manifest_is_consequential = False

    # FastMCP supports `meta` and `annotations`; tests and UI rely on these.
    #
    # In compact mode, keep the metadata surface minimal to avoid connector
    # prompts on every call. Expanded metadata (including OpenAI-specific
    # hints) can be re-enabled via the ``GITHUB_MCP_COMPACT_METADATA`` flag.
    meta: dict[str, Any] = {
        "write_action": False,
        "auto_approved": True,
        "visibility": visibility,
        # These hint the connector/UI about whether a tool mutates state. Keep
        # them even in compact metadata mode so read actions surface as READ
        # instead of WRITE in clients that rely on OpenAI-flavored fields.
        "openai/isConsequential": manifest_is_consequential,
        "x-openai-isConsequential": manifest_is_consequential,
    }
    if not compact_metadata:
        meta.update(
            {
                # OpenAI connector UI metadata (Apps & Connectors).
                # These keys are intentionally flat (not nested) because
                # OpenAI's connector UI historically reads them from `meta` directly.
                "openai/visibility": visibility,
                "openai/toolInvocation/invoking": openai_invoking_message
                or OPENAI_INVOKING_MESSAGE,
                "openai/toolInvocation/invoked": openai_invoked_message
                or OPENAI_INVOKED_MESSAGE,
            }
        )
    if title and not compact_metadata:
        # Helpful for UIs that support a distinct display label.
        meta["title"] = title
        meta["openai/title"] = title

    # Drop any user-provided metadata that could leak location details.
    meta = strip_location_metadata(meta)
    annotations = {
        "readOnlyHint": True,
        "title": title or _title_from_tool_name(name),
        "isConsequential": manifest_is_consequential,
    }

    tool_obj = mcp.tool(
        fn,
        name=name,
        description=description,
        tags=tags,
        meta=meta,
        annotations=annotations,
    )

    try:
        tool_obj.parameters = _normalize_input_schema(tool_obj)
    except Exception:
        # Schema population should never block registration; fall back to
        # FastMCP defaults if normalization fails.
        pass

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
    write_action: bool = False,
    tags: Optional[Iterable[str]] = None,
    description: str | None = None,
    visibility: str = "public",
    ui_consequential: bool | None = None,
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
                    result = _sanitize_tool_result(result)
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
                    result = _sanitize_tool_result(result)
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

        openai_is_consequential = _openai_is_consequential(
            tool_name, tag_set, write_action=write_action, ui_consequential=ui_consequential
        )

        _register_with_fastmcp(
            wrapper,
            name=tool_name,
            title=tool_title,
            description=normalized_description,
            tags=tag_set,
            write_action=write_action,
            openai_is_consequential=openai_is_consequential,
            visibility=tool_visibility,
            openai_invoking_message=invoking_msg,
            openai_invoked_message=invoked_msg,
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

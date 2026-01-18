"""Decorators and helpers for registering MCP tools.

This module provides the primary `mcp_tool` decorator and related utilities.
It also includes optional, best-effort request deduplication helpers used by
the server and tests.
"""

from __future__ import annotations

import asyncio
import inspect
import functools
import hashlib
import importlib
import inspect
import json
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from github_mcp.config import (
    BASE_LOGGER,
    HUMAN_LOGS,
    LOG_INLINE_CONTEXT,
    LOG_TOOL_CALL_STARTS,
    LOG_TOOL_CALLS,
    LOG_TOOL_PAYLOADS,
    format_log_context,
    shorten_token,
    snapshot_request_context,
    summarize_request_context,
)
from github_mcp.exceptions import UsageError
from github_mcp.mcp_server.context import (
    FASTMCP_AVAILABLE,
    WRITE_ALLOWED,
    get_request_context,
    mcp,
)
from github_mcp.mcp_server.error_handling import _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS, _registered_tool_name
from github_mcp.redaction import redact_any
from github_mcp.mcp_server.schemas import (
    _build_tool_docstring,
    _normalize_input_schema,
    _normalize_tool_description,
    _schema_from_signature,
)

# Intentionally short logger name; config's formatter further shortens/colorizes.
LOGGER = BASE_LOGGER.getChild("mcp")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _running_under_pytest() -> bool:
    """Return True when executing under pytest.

    Pytest sets the PYTEST_CURRENT_TEST environment variable for each active
    test. We use this to keep unit tests deterministic even if operator-facing
    environment variables (e.g., response shaping) are enabled in the runtime.
    """

    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _is_render_runtime() -> bool:
    """Best-effort detection for Render deployments.

    Render sets a number of standard environment variables for running services.
    We use these signals to tune provider-facing defaults.
    """

    return any(
        os.environ.get(name)
        for name in (
            "RENDER",
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_EXTERNAL_URL",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_COMMIT",
        )
    )


# Visual logging (developer-facing).
#
# Render and similar providers often display only the message string, so these
# helpers emit compact, scan-friendly previews for:
#   - diffs / patches
#   - workspace changes (git status porcelain)
#   - file reads (file + snippet with line numbers)
#
# ANSI color is enabled by default for developer-facing usage.
# If your log UI does not interpret escape sequences, disable via:
#   GITHUB_MCP_LOG_COLOR=0
LOG_TOOL_VISUALS = _env_flag("GITHUB_MCP_LOG_VISUALS", default=True)
LOG_TOOL_COLOR = _env_flag("GITHUB_MCP_LOG_COLOR", default=True)
LOG_TOOL_READ_SNIPPETS = _env_flag("GITHUB_MCP_LOG_READ_SNIPPETS", default=True)
LOG_TOOL_DIFF_SNIPPETS = _env_flag("GITHUB_MCP_LOG_DIFF_SNIPPETS", default=True)
LOG_TOOL_STYLE = os.environ.get("GITHUB_MCP_LOG_STYLE", "monokai")

# Whether to include Python tracebacks in provider logs for tool failures.
#
# Hosted providers (Render) already surface structured errors well, and emitting
# `exc_info` can create extremely verbose log streams. Default to disabling
# exception tracebacks on Render unless explicitly enabled.
LOG_TOOL_EXC_INFO = _env_flag(
    "GITHUB_MCP_LOG_EXC_INFO",
    default=(not _is_render_runtime()),
)

# Reduce log noise by omitting correlation IDs from INFO/WARN message strings.
# Structured extras (appended by the provider log formatter) still include the
# full request context.
LOG_TOOL_LOG_IDS = _env_flag("GITHUB_MCP_LOG_IDS", default=False)

# Emit one request snapshot line and one response snapshot line per tool call.
# This is enabled by default because provider log UIs are optimized for
# scan-friendly summaries.
LOG_TOOL_SNAPSHOTS = _env_flag("GITHUB_MCP_LOG_SNAPSHOTS", default=True)

# When enabled, include deeper diagnostic fields in provider extras.
# This is intentionally off by default to keep logs scan-friendly.
LOG_TOOL_VERBOSE_EXTRAS = _env_flag("GITHUB_MCP_LOG_VERBOSE_EXTRAS", default=False)

# Tool result envelope
#
# Many clients benefit from a consistent, machine-readable success/warning/error
# surface. Tool implementations historically returned heterogeneous payloads.
#
# This envelope normalizes *mapping* (dict-like) results by adding:
#   - ok: bool
#   - status: success|warning|error
#   - warnings: list[str] (only when warning)
#
# Scalar/list results are preserved by default for backward compatibility.
# IMPORTANT: default is False to preserve the repo's compatibility contract:
# tool return values must not be mutated by the wrapper.
TOOL_RESULT_ENVELOPE = _env_flag("GITHUB_MCP_TOOL_RESULT_ENVELOPE", default=False)
TOOL_RESULT_ENVELOPE_SCALARS = _env_flag("GITHUB_MCP_TOOL_RESULT_ENVELOPE_SCALARS", default=False)

# Tool response shaping
#
# Some clients (including ChatGPT-hosted connectors) benefit from consistently
# shaped tool responses that:
# - always include ok/status
# - avoid huge nested blobs (e.g., raw upstream JSON)
# - are easy to scan without reading provider logs
#
# This is intentionally opt-in via env var. If you set it to "chatgpt", the
# decorator will wrap scalar outputs, add ok/status when missing, and truncate
# very large nested "json" payloads.
RESPONSE_MODE_DEFAULT = os.environ.get("GITHUB_MCP_RESPONSE_MODE", "raw").strip().lower()
CHATGPT_RESPONSE_MAX_LIST_ITEMS = _env_int("GITHUB_MCP_RESPONSE_MAX_LIST_ITEMS", default=0)

# In hosted LLM connector environments, returning token-like strings (even from
# test fixtures or diffs) can trigger upstream safety filters and block tool
# outputs. Redaction is therefore enabled by default, with an escape hatch.
REDACT_TOOL_OUTPUTS = _env_flag("GITHUB_MCP_REDACT_TOOL_OUTPUTS", default=True)


def _effective_response_mode(req: Mapping[str, Any] | None = None) -> str:
    """Determine response shaping mode.

    - If GITHUB_MCP_RESPONSE_MODE is set to a non-raw value, honor it.
    - Otherwise, if the inbound request includes ChatGPT metadata, default to
      'chatgpt' (ChatGPT-hosted connectors benefit from consistent, compact outputs).
    """
    if _running_under_pytest():
        return "raw"

    mode = (RESPONSE_MODE_DEFAULT or "raw").strip().lower()
    if mode and mode not in {"raw", "default"}:
        return mode
    if isinstance(req, Mapping):
        cg = req.get("chatgpt")
        if isinstance(cg, Mapping) and cg:
            return "chatgpt"
    return "raw"


LOG_TOOL_VISUAL_MAX_LINES = _env_int("GITHUB_MCP_LOG_VISUAL_MAX_LINES", default=80)
LOG_TOOL_READ_MAX_LINES = _env_int("GITHUB_MCP_LOG_READ_MAX_LINES", default=40)
LOG_TOOL_VISUAL_MAX_CHARS = _env_int("GITHUB_MCP_LOG_VISUAL_MAX_CHARS", default=8000)


ANSI_RESET = "\x1b[0m"
ANSI_DIM = "\x1b[2m"
ANSI_RED = "\x1b[31m"
ANSI_GREEN = "\x1b[32m"
ANSI_YELLOW = "\x1b[33m"
ANSI_CYAN = "\x1b[36m"


_ADAPTIV_MCP_METADATA = {
    "provider": "Adaptiv MCP",
    "server": "github-mcp",
    "connected": True,
}


def _inject_adaptiv_mcp_metadata(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    out = dict(payload)
    if "adaptiv_mcp" not in out:
        out["adaptiv_mcp"] = dict(_ADAPTIV_MCP_METADATA)
    return out


def _pygments_available() -> bool:
    try:
        import pygments  # noqa: F401

        return True
    except Exception:
        return False


def _highlight_code(text: str, *, kind: str = "text") -> str:
    """Best-effort syntax highlighting for log visuals.

    Uses Pygments if installed and ANSI color is enabled.
    """

    if not (LOG_TOOL_COLOR and _pygments_available() and isinstance(text, str) and text):
        return text
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import (
            DiffLexer,
            PythonLexer,
            PythonTracebackLexer,
            TextLexer,
        )

        if kind == "diff":
            lexer = DiffLexer()
        elif kind == "traceback":
            lexer = PythonTracebackLexer()
        elif kind == "python":
            lexer = PythonLexer()
        else:
            lexer = TextLexer()
        return highlight(text, lexer, Terminal256Formatter(style=LOG_TOOL_STYLE)).rstrip("\n")
    except Exception:
        return text


def _highlight_file_text(path: str, text: str) -> str:
    """Highlight file text by filename when possible."""

    if not (LOG_TOOL_COLOR and _pygments_available() and isinstance(text, str) and text):
        return text
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import TextLexer, get_lexer_for_filename

        try:
            lexer = get_lexer_for_filename(path or "", text)
        except Exception:
            lexer = TextLexer()
        return highlight(text, lexer, Terminal256Formatter(style=LOG_TOOL_STYLE)).rstrip("\n")
    except Exception:
        return text


def _highlight_line_for_filename(path: str, text: str) -> str:
    """Syntax-highlight a single line of text using the filename for lexer selection."""

    if not (LOG_TOOL_COLOR and _pygments_available() and isinstance(text, str) and text):
        return text
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import TextLexer, get_lexer_for_filename

        try:
            lexer = get_lexer_for_filename(path or "", text)
        except Exception:
            lexer = TextLexer()
        return highlight(text, lexer, Terminal256Formatter(style=LOG_TOOL_STYLE)).rstrip("\n")
    except Exception:
        return text


def _ansi(text: str, code: str) -> str:
    if not LOG_TOOL_COLOR:
        return text
    return f"{code}{text}{ANSI_RESET}"


def _inline_context(req: Mapping[str, Any]) -> str:
    """Return compact correlation context for single-line logs."""

    if not LOG_INLINE_CONTEXT:
        return ""
    try:
        return format_log_context(req) or ""
    except Exception as exc:
        # Best-effort: do not break tool logging, but make failures visible.
        try:
            LOGGER.debug("Failed to format inline log context", exc_info=exc)
        except Exception:
            pass
        return ""


# Friendly tool naming for developer-facing logs.
_TOOL_FRIENDLY_NAMES: dict[str, str] = {
    "validate_environment": "Environment check",
    "get_server_config": "Server config",
    "ensure_workspace_clone": "Workspace sync",
    "workspace_create_branch": "Create branch",
    "workspace_delete_branch": "Delete branch",
    "commit_workspace": "Commit changes",
    "commit_workspace_files": "Commit selected files",
    "get_workspace_changes_summary": "Workspace changes",
    "build_pr_summary": "Build PR summary",
    "commit_and_open_pr_from_workspace": "Commit and open PR",
    "open_pr_for_existing_branch": "Open pull request",
    "apply_patch": "Apply patch",
    "get_workspace_file_contents": "Read file",
    "set_workspace_file_contents": "Write file",
    "edit_workspace_text_range": "Edit text range",
    "edit_workspace_line": "Edit line",
    "replace_workspace_text": "Replace text",
    "delete_workspace_paths": "Delete paths",
    "move_workspace_paths": "Move paths",
    "apply_workspace_operations": "Apply workspace operations",
    "list_workspace_files": "List files",
    "search_workspace": "Search workspace",
    "terminal_command": "Run command",
    "render_shell": "Run shell",
    "workspace_self_heal_branch": "Self-heal branch",
    "workspace_sync_status": "Workspace sync status",
    "workspace_sync_to_remote": "Sync to remote",
    "workspace_sync_bidirectional": "Bidirectional sync",
    "run_quality_suite": "Quality suite",
    "run_lint_suite": "Lint suite",
    "run_tests": "Test suite",
}


def _friendly_tool_name(tool_name: str) -> str:
    name = _TOOL_FRIENDLY_NAMES.get(str(tool_name))
    if name:
        return name
    return str(tool_name).replace("_", " ").strip().title() or str(tool_name)


def _friendly_arg_bits(all_args: Mapping[str, Any]) -> list[str]:
    """Convert common args into short, human-readable fragments."""

    bits: list[str] = []
    if not isinstance(all_args, Mapping):
        return bits

    full_name = all_args.get("full_name")
    ref = all_args.get("ref")
    if isinstance(full_name, str) and full_name:
        if isinstance(ref, str) and ref:
            bits.append(f"{full_name}@{ref}")
        else:
            bits.append(full_name)

    path = all_args.get("path")
    if isinstance(path, str) and path:
        bits.append(path)

    paths = all_args.get("paths")
    if isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths):
        show = paths[:3]
        tail = f" (+{len(paths) - len(show)} more)" if len(paths) > len(show) else ""
        bits.append(", ".join(show) + tail)

    title = all_args.get("title")
    if isinstance(title, str) and title.strip():
        bits.append(f'"{title.strip()}"')

    base = all_args.get("base") or all_args.get("base_ref")
    head = all_args.get("head") or all_args.get("branch") or all_args.get("new_branch")
    if isinstance(head, str) and head:
        if isinstance(base, str) and base:
            bits.append(f"{head} -> {base}")
        else:
            bits.append(head)

    # File list variants (commit_workspace_files)
    files = all_args.get("files")
    if isinstance(files, list) and files and all(isinstance(p, str) for p in files):
        show = files[:3]
        tail = f" (+{len(files) - len(show)} more)" if len(files) > len(show) else ""
        bits.append(", ".join(show) + tail)

    # Common edit parameters.
    operation = all_args.get("operation")
    if isinstance(operation, str) and operation:
        bits.append(operation)
    line_number = all_args.get("line_number")
    if isinstance(line_number, int) and line_number > 0:
        bits.append(f"L{line_number}")
    start_line = all_args.get("start_line")
    end_line = all_args.get("end_line")
    if isinstance(start_line, int) and isinstance(end_line, int):
        start_col = all_args.get("start_col")
        end_col = all_args.get("end_col")
        if isinstance(start_col, int) and isinstance(end_col, int):
            bits.append(f"{start_line}:{start_col}-{end_line}:{end_col}")
        else:
            bits.append(f"{start_line}-{end_line}")

    # Search / listing.
    path_prefix = all_args.get("path_prefix")
    if isinstance(path_prefix, str) and path_prefix.strip():
        bits.append(f"prefix={path_prefix.strip()}")

    # Flags (only show when True to reduce noise).
    for key in ("draft", "run_quality", "replace_all", "discard_local_changes"):
        val = all_args.get(key)
        if val is True:
            bits.append(f"{key}=true")

    occurrence = all_args.get("occurrence")
    if isinstance(occurrence, int) and occurrence > 1:
        bits.append(f"occurrence={occurrence}")

    cmd = all_args.get("command")
    if isinstance(cmd, str) and cmd.strip():
        bits.append(cmd.strip())
    cmd_lines = all_args.get("command_lines")
    if isinstance(cmd_lines, list) and cmd_lines and all(isinstance(x, str) for x in cmd_lines):
        first = cmd_lines[0].strip()
        if first:
            bits.append(first + (f" (+{len(cmd_lines) - 1} more)" if len(cmd_lines) > 1 else ""))

    return bits


def _clip_text(text: str, *, max_lines: int, max_chars: int) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    clipped = lines[: max(0, max_lines)]
    out = "\n".join(clipped)
    if len(lines) > max_lines:
        out += "\n" + _ansi(f"… ({len(lines) - max_lines} more lines)", ANSI_DIM)
    if len(out) > max_chars:
        out = out[: max(0, max_chars - 1)] + "…"
    return out


_DIFF_HEADER_RE = re.compile(r"^(diff --git|\+\+\+ |--- |@@ )")
_DIFF_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def _looks_like_unified_diff(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    sample = "\n".join(text.splitlines()[:25])
    return bool(_DIFF_HEADER_RE.search(sample))


def _non_ansi_diff_markers(diff_text: str) -> str:
    """Fallback diff formatting when ANSI is disabled."""

    out: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(f"[FILE] {line}")
        elif line.startswith("@@"):
            out.append(f"[HUNK] {line}")
        elif line.startswith("+"):
            out.append(f"[ADD]  {line}")
        elif line.startswith("-"):
            out.append(f"[DEL]  {line}")
        else:
            out.append(line)
    return "\n".join(out)


def _preview_unified_diff(diff_text: str) -> str:
    """Preview a unified diff with file-accurate line numbers.

    The output resembles an editor diff view:
      <old_ln> <new_ln> │ <prefix><code>
    where old/new line numbers advance per hunk header.
    """

    if not diff_text:
        return ""

    header = "diff"
    try:
        from github_mcp.diff_utils import diff_stats

        stats = diff_stats(diff_text)
        header = f"diff (+{stats.added} -{stats.removed})"
    except Exception:
        pass

    # Best-effort parse; fall back to a simple numbered listing if parsing fails.
    try:
        rendered = _render_rich_unified_diff(diff_text)
    except Exception:
        body = (
            _highlight_code(diff_text, kind="diff")
            if LOG_TOOL_COLOR
            else _non_ansi_diff_markers(diff_text)
        )
        numbered: list[str] = []
        for idx, line in enumerate(body.splitlines(), start=1):
            ln = _ansi(f"{idx:>4}│", ANSI_DIM)
            numbered.append(f"{ln} {line}")
        rendered = "\n".join(numbered)

    clipped = _clip_text(
        rendered,
        max_lines=LOG_TOOL_VISUAL_MAX_LINES,
        max_chars=LOG_TOOL_VISUAL_MAX_CHARS,
    )
    return _ansi(header, ANSI_CYAN) + "\n" + clipped


def _render_rich_unified_diff(diff_text: str) -> str:
    current_path = ""
    old_ln: Optional[int] = None
    new_ln: Optional[int] = None

    out: list[str] = []
    for raw in (diff_text or "").splitlines():
        line = raw.rstrip("\n")

        if line.startswith("diff --git "):
            old_ln = None
            new_ln = None
            out.append(_ansi(line, ANSI_DIM) if LOG_TOOL_COLOR else line)
            continue
        if line.startswith("index "):
            out.append(_ansi(line, ANSI_DIM) if LOG_TOOL_COLOR else line)
            continue
        if line.startswith("--- "):
            out.append(_ansi(line, ANSI_DIM) if LOG_TOOL_COLOR else line)
            continue
        if line.startswith("+++ "):
            # Track the "new" path for syntax highlighting when possible.
            # Prefer b/<path> but accept whatever is present.
            current_path = line[4:].strip()
            if current_path.startswith("b/"):
                current_path = current_path[2:]
            out.append(_ansi(line, ANSI_DIM) if LOG_TOOL_COLOR else line)
            continue

        if line.startswith("@@"):
            m = _DIFF_HUNK_RE.match(line)
            if m:
                old_ln = int(m.group(1))
                new_ln = int(m.group(3))
            else:
                old_ln = None
                new_ln = None
            out.append(_ansi(line, ANSI_YELLOW) if LOG_TOOL_COLOR else f"[HUNK] {line}")
            continue

        # Hunk content
        if old_ln is None or new_ln is None:
            # Not in a hunk yet; render verbatim.
            out.append(_highlight_code(line, kind="diff") if LOG_TOOL_COLOR else line)
            continue

        prefix = line[:1] if line else ""
        content = line[1:] if len(line) > 1 else ""

        old_cell = ""
        new_cell = ""
        colored_prefix = prefix

        if prefix == " ":
            old_cell = f"{old_ln:>5}"
            new_cell = f"{new_ln:>5}"
            old_ln += 1
            new_ln += 1
            if LOG_TOOL_COLOR:
                colored_prefix = _ansi(" ", ANSI_DIM)
        elif prefix == "-" and not line.startswith("---"):
            old_cell = f"{old_ln:>5}"
            new_cell = " " * 5
            old_ln += 1
            if LOG_TOOL_COLOR:
                colored_prefix = _ansi("-", ANSI_RED)
        elif prefix == "+" and not line.startswith("+++"):
            old_cell = " " * 5
            new_cell = f"{new_ln:>5}"
            new_ln += 1
            if LOG_TOOL_COLOR:
                colored_prefix = _ansi("+", ANSI_GREEN)
        else:
            old_cell = " " * 5
            new_cell = " " * 5
            if LOG_TOOL_COLOR:
                colored_prefix = _ansi(prefix or " ", ANSI_DIM)

        # Syntax highlight the content as file text (best-effort), preserving diff prefix coloring.
        rendered_content = (
            _highlight_line_for_filename(current_path, content) if LOG_TOOL_COLOR else content
        )

        gutter = f"{old_cell} {new_cell} {_ansi('│', ANSI_DIM) if LOG_TOOL_COLOR else '|'}"
        out.append(f"{gutter} {colored_prefix}{rendered_content}")

    return "\n".join(out)


def _preview_terminal_result(payload: Mapping[str, Any]) -> str:
    """Preview stdout/stderr from terminal_command results with line numbers."""

    result = payload.get("result") if isinstance(payload, Mapping) else None
    if not isinstance(result, Mapping):
        return ""

    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    exit_code = result.get("exit_code")

    # Prefer stderr, but include stdout if stderr is empty.
    combined = ""
    if isinstance(stderr, str) and stderr.strip():
        combined = stderr
    elif isinstance(stdout, str) and stdout.strip():
        combined = stdout
    if not combined:
        return ""

    kind = "text"
    if "Traceback (most recent call last):" in combined:
        kind = "traceback"
    elif _looks_like_unified_diff(combined):
        kind = "diff"
    elif 'File "' in combined and "line" in combined and "Error" in combined:
        kind = "traceback"

    highlighted = _highlight_code(combined, kind=kind)
    lines = highlighted.splitlines()
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    preview = lines[:max_lines]
    rendered: list[str] = []
    for idx, line in enumerate(preview, start=1):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        rendered.append(f"{ln} {line}")
    if len(lines) > max_lines:
        rendered.append(_ansi(f"… ({len(lines) - max_lines} more lines)", ANSI_DIM))

    header_bits = ["terminal"]
    if exit_code is not None:
        header_bits.append(f"exit={exit_code}")
    header = " ".join(header_bits)
    return (
        _ansi(header, ANSI_CYAN)
        + "\n"
        + _clip_text(
            "\n".join(rendered),
            max_lines=LOG_TOOL_VISUAL_MAX_LINES,
            max_chars=LOG_TOOL_VISUAL_MAX_CHARS,
        )
    )


def _format_stream_block(
    text: str,
    *,
    label: str,
    header_color: str,
    max_lines: int,
    max_chars: int,
) -> str:
    """Render a stdout/stderr block with line numbers and ANSI coloring."""

    if not isinstance(text, str) or not text:
        return ""

    # Best-effort classification for highlighting.
    kind = "text"
    if "Traceback (most recent call last):" in text:
        kind = "traceback"
    elif _looks_like_unified_diff(text):
        kind = "diff"
    elif 'File "' in text and "line" in text and "Error" in text:
        kind = "traceback"

    highlighted = _highlight_code(text, kind=kind)
    lines = highlighted.splitlines()
    preview = lines[: max(1, max_lines)]
    rendered: list[str] = []
    for idx, line in enumerate(preview, start=1):
        rendered.append(f"{_ansi(f'{idx:>4}│', ANSI_DIM)} {line}")
    if len(lines) > max_lines:
        rendered.append(_ansi(f"… ({len(lines) - max_lines} more lines)", ANSI_DIM))

    header = _ansi(label, header_color)
    return header + "\n" + _clip_text("\n".join(rendered), max_lines=max_lines, max_chars=max_chars)


def _inject_stdout_stderr(out: dict[str, Any]) -> None:
    """Attach stdout/stderr to ChatGPT-friendly responses.

    Many tools return process outputs nested under `result`. ChatGPT UIs often
    benefit from having these streams available at the top-level.

    Adds:
    - stdout / stderr (raw strings)
    - stdout_colored / stderr_colored (ANSI + line numbers, clipped)
    """

    if not isinstance(out, dict):
        return

    # Accept both top-level and nested result envelopes.
    result = out.get("result")
    inner = result if isinstance(result, Mapping) else out

    stdout = inner.get("stdout") if isinstance(inner, Mapping) else None
    stderr = inner.get("stderr") if isinstance(inner, Mapping) else None

    if isinstance(stdout, str) and stdout and "stdout" not in out:
        out["stdout"] = stdout
    if isinstance(stderr, str) and stderr and "stderr" not in out:
        out["stderr"] = stderr

    # Render colorized blocks (even when LOG_TOOL_COLOR is off) because this is
    # explicitly requested for ChatGPT-facing payloads.
    max_lines = max(1, LOG_TOOL_VISUAL_MAX_LINES)
    max_chars = max(1, LOG_TOOL_VISUAL_MAX_CHARS)

    if isinstance(stdout, str) and stdout.strip():
        out.setdefault(
            "stdout_colored",
            _format_stream_block(
                stdout,
                label="stdout",
                header_color=ANSI_GREEN,
                max_lines=max_lines,
                max_chars=max_chars,
            ),
        )

    if isinstance(stderr, str) and stderr.strip():
        out.setdefault(
            "stderr_colored",
            _format_stream_block(
                stderr,
                label="stderr",
                header_color=ANSI_RED,
                max_lines=max_lines,
                max_chars=max_chars,
            ),
        )


def _preview_changed_files(status_lines: list[str]) -> str:
    if not status_lines:
        return ""

    rendered: list[str] = []
    for raw in status_lines[:LOG_TOOL_VISUAL_MAX_LINES]:
        line = (raw or "").rstrip("\n")
        if not line:
            continue
        code = line[:2]
        path = line[3:] if len(line) > 3 else ""
        # Porcelain status heuristics
        tag = code.strip() or "??"
        if "?" in code:
            prefix = _ansi("??", ANSI_DIM)
        elif "A" in code:
            prefix = _ansi("A ", ANSI_GREEN)
        elif "D" in code:
            prefix = _ansi("D ", ANSI_RED)
        elif "R" in code:
            prefix = _ansi("R ", ANSI_CYAN)
        else:
            prefix = _ansi("M ", ANSI_YELLOW)
        rendered.append(f"{prefix} {_ansi(path, ANSI_CYAN) if path else tag}")

    if len(status_lines) > LOG_TOOL_VISUAL_MAX_LINES:
        rendered.append(
            _ansi(f"… ({len(status_lines) - LOG_TOOL_VISUAL_MAX_LINES} more files)", ANSI_DIM)
        )

    return _ansi("workspace_changes", ANSI_CYAN) + "\n" + "\n".join(rendered)


_PORCELAIN_RE = re.compile(r"^[ MADRCU?]{2} ")


def _is_porcelain_status_list(lines: list[str]) -> bool:
    if not lines:
        return False
    checked = 0
    ok = 0
    for raw in lines[:50]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        checked += 1
        if _PORCELAIN_RE.match(raw):
            ok += 1
    # Require most lines to match to avoid mis-classifying file listings.
    return checked > 0 and (ok / checked) >= 0.8


def _preview_file_snippet(path: str, text: str, *, start_line: int = 1) -> str:
    highlighted = _highlight_file_text(path, text or "")
    lines = highlighted.splitlines()
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    preview = lines[:max_lines]
    rendered: list[str] = []
    start_line = max(1, int(start_line))
    for idx, line in enumerate(preview, start=start_line):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        rendered.append(f"{ln} {line}")
    if len(lines) > max_lines:
        rendered.append(_ansi(f"… ({len(lines) - max_lines} more lines)", ANSI_DIM))

    header = f"read {_ansi(path, ANSI_CYAN) if path else ''}".rstrip()
    return (
        _ansi(header, ANSI_CYAN)
        + "\n"
        + _clip_text(
            "\n".join(rendered),
            max_lines=LOG_TOOL_VISUAL_MAX_LINES,
            max_chars=LOG_TOOL_VISUAL_MAX_CHARS,
        )
    )


def _preview_file_list(paths: list[str], *, header: str = "files") -> str:
    if not paths:
        return ""
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    rendered: list[str] = []
    for idx, p in enumerate(paths[:max_lines], start=1):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        rendered.append(f"{ln} {_ansi(p, ANSI_CYAN) if LOG_TOOL_COLOR else p}")
    if len(paths) > max_lines:
        rendered.append(_ansi(f"… ({len(paths) - max_lines} more)", ANSI_DIM))
    return _ansi(header, ANSI_CYAN) + "\n" + "\n".join(rendered)


def _preview_search_hits(hits: list[Mapping[str, Any]]) -> str:
    if not hits:
        return ""
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    rendered: list[str] = []
    for idx, hit in enumerate(hits[:max_lines], start=1):
        file = str(hit.get("file") or "")
        line_no = hit.get("line")
        text = str(hit.get("text") or "")
        loc = f"{file}:{line_no}" if file and isinstance(line_no, int) else file
        loc = _ansi(loc, ANSI_CYAN) if LOG_TOOL_COLOR else loc
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        rendered.append(f"{ln} {loc} {text}".rstrip())
    if len(hits) > max_lines:
        rendered.append(_ansi(f"… ({len(hits) - max_lines} more hits)", ANSI_DIM))
    return _ansi("search", ANSI_CYAN) + "\n" + "\n".join(rendered)


def _preview_json_objects(items: list[Any], *, header: str) -> str:
    """Preview list[dict] payloads from provider APIs (e.g., Render)."""

    if not items:
        return ""
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    rendered: list[str] = []
    for idx, item in enumerate(items[:max_lines], start=1):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        if isinstance(item, Mapping):
            name = item.get("name") or item.get("service") or item.get("type")
            ident = item.get("id") or item.get("serviceId") or item.get("deployId")
            bits: list[str] = []
            if ident:
                bits.append(str(ident))
            if name:
                bits.append(str(name))
            line = " - ".join(bits) if bits else _truncate_text(item, limit=140)
        else:
            line = _truncate_text(item, limit=140)
        rendered.append(f"{ln} {line}")
    if len(items) > max_lines:
        rendered.append(_ansi(f"… ({len(items) - max_lines} more)", ANSI_DIM))
    return _ansi(header, ANSI_CYAN) + "\n" + "\n".join(rendered)


def _render_extract_list(body: Any) -> list[Any] | None:
    """Extract a representative list from a Render API json payload."""

    if isinstance(body, list):
        return body
    if not isinstance(body, Mapping):
        return None

    # Render endpoints vary: some return a bare list; others wrap under keys.
    for key in (
        "logs",
        "items",
        "services",
        "deploys",
        "owners",
        "envVars",
        "events",
    ):
        val = body.get(key)
        if isinstance(val, list):
            return val
    # Otherwise pick the first list-like value.
    for _k, v in body.items():
        if isinstance(v, list):
            return v
    return None


def _preview_render_logs(items: list[Any]) -> str:
    if not items:
        return ""
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    rendered: list[str] = []
    for idx, item in enumerate(items[:max_lines], start=1):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        if isinstance(item, Mapping):
            ts = item.get("timestamp") or item.get("time") or item.get("createdAt")
            level = item.get("level") or item.get("severity")
            msg = item.get("message") or item.get("text") or item.get("log")
            bits: list[str] = []
            if ts:
                bits.append(str(ts))
            if level:
                lvl = str(level)
                if LOG_TOOL_COLOR:
                    if lvl.lower().startswith("err"):
                        lvl = _ansi(lvl, ANSI_RED)
                    elif lvl.lower().startswith("warn"):
                        lvl = _ansi(lvl, ANSI_YELLOW)
                    else:
                        lvl = _ansi(lvl, ANSI_GREEN)
                bits.append(lvl)
            if msg:
                # Render log messages can include large JSON payloads and full tracebacks.
                # Keep previews single-line and bounded to avoid flooding provider logs.
                bits.append(_truncate_text(msg, limit=240))
            line = " ".join(bits) if bits else _truncate_text(item, limit=180)
        else:
            line = _truncate_text(item, limit=180)
        rendered.append(f"{ln} {line}")
    if len(items) > max_lines:
        rendered.append(_ansi(f"… ({len(items) - max_lines} more)", ANSI_DIM))
    return _ansi("render_logs", ANSI_CYAN) + "\n" + "\n".join(rendered)


def _log_tool_visual(
    *,
    tool_name: str,
    call_id: str,
    req: Mapping[str, Any],
    kind: str,
    visual: str,
) -> None:
    if not visual:
        return
    if not (LOG_TOOL_CALLS and HUMAN_LOGS and LOG_TOOL_VISUALS):
        return

    kv_map: dict[str, Any] = {"kind": kind}
    if LOG_TOOL_LOG_IDS:
        req_ctx = summarize_request_context(req)
        kv_map.update(
            {
                "call_id": shorten_token(call_id),
                "session_id": req_ctx.get("session_id"),
                "message_id": req_ctx.get("message_id"),
            }
        )
    kv = _format_log_kv(kv_map)
    header = (
        _ansi(kind or "visual", ANSI_CYAN) + " " + _ansi(_friendly_tool_name(tool_name), ANSI_CYAN)
    )
    if kv:
        header = header + " " + kv
    inline = _inline_context(req)
    if inline:
        header = header + " " + _ansi(inline, ANSI_DIM)
    LOGGER.info(
        f"{header}\n{visual}",
        extra={
            "event": "tool_visual",
            "tool": tool_name,
            "kind": kind,
            "call_id": shorten_token(call_id),
            "request": snapshot_request_context(req),
            "log_context": inline or None,
        },
    )


def _truncate_text(value: Any, *, limit: int = 180) -> str:
    def scalar(v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return str(v)

    try:
        if isinstance(value, str):
            s = value
        elif isinstance(value, Mapping):
            preferred = [
                "id",
                "name",
                "full_name",
                "path",
                "status",
                "state",
                "type",
                "message",
                "url",
            ]
            parts: list[str] = []
            for key in preferred:
                if key in value and value.get(key) is not None:
                    parts.append(f"{key}={scalar(value.get(key))}")
            if not parts:
                for k in sorted(list(value.keys()))[:6]:
                    if value.get(k) is None:
                        continue
                    parts.append(f"{k}={scalar(value.get(k))}")
            s = ", ".join(parts) if parts else "(object)"
        elif isinstance(value, list):
            if not value:
                s = "(empty list)"
            else:
                head = ", ".join(scalar(v) for v in value[:6])
                tail = f" (+{len(value) - 6} more)" if len(value) > 6 else ""
                s = f"[{head}{tail}]"
        else:
            s = str(value)
    except Exception:
        s = str(value)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "pat",
    "secret",
    "password",
    "passwd",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
)


def _is_sensitive_key(key: str) -> bool:
    lk = key.lower()
    return any(fragment in lk for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _args_summary(all_args: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact, developer-friendly subset of args for log lines.

    This is meant for provider logs where only the message string is easily
    visible (e.g., Render). It intentionally excludes payload-sized fields and
    secret-like keys.

    Sensitive fields can be included by setting:
      GITHUB_MCP_LOG_SENSITIVE=1
    """

    if not isinstance(all_args, Mapping) or not all_args:
        return {}

    allow_sensitive = _env_flag("GITHUB_MCP_LOG_SENSITIVE", default=False)
    candidates = (
        # Repo identity
        "full_name",
        "owner",
        "repo",
        # Refs
        "ref",
        "branch",
        "base_ref",
        "base",
        "head",
        # Paths/queries
        "path",
        "paths",
        "query",
        "pattern",
        # PR-ish
        "title",
        "number",
        # Workspace
        "reset",
        # Commands / patches (truncate)
        "command",
        "command_lines",
        "patch",
        # Misc
        "schedule",
    )

    out: dict[str, Any] = {}
    for key in candidates:
        if key not in all_args:
            continue
        if (not allow_sensitive) and _is_sensitive_key(key):
            continue
        val = all_args.get(key)
        if val is None:
            continue
        # Avoid massive payloads.
        if key in {"patch"}:
            out[key] = _truncate_text(val, limit=160)
        elif key in {"command"}:
            out[key] = _truncate_text(val, limit=160)
        elif key in {"command_lines"}:
            # Keep only first few command lines.
            if isinstance(val, list):
                out[key] = [_truncate_text(v, limit=120) for v in val[:3]]
            else:
                out[key] = _truncate_text(val, limit=160)
        else:
            out[key] = _truncate_text(val, limit=160)

    return out


def _format_log_kv(data: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for k, v in data.items():
        if v is None:
            continue
        if v == "":
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)


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

    __slots__ = ("name", "description", "input_schema", "meta", "annotations")

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
        self.annotations: dict[str, Any] = {}

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
    tags: Optional[Iterable[str]] = None,
    *,
    write_action: Optional[bool] = None,  # noqa: ARG001
    write_allowed: Optional[bool] = None,  # noqa: ARG001
    ui: Optional[Mapping[str, Any]] = None,
) -> None:
    """Attach metadata onto the registered tool object.

    The tool wrapper remains the source of truth for behavior. The tool object
    metadata is intended for discovery/UIs.
    """

    if tool_obj is None:
        return

    meta = getattr(tool_obj, "meta", None)
    if not isinstance(meta, dict):
        if isinstance(tool_obj, dict):
            meta = tool_obj.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                tool_obj["meta"] = meta
        else:
            try:
                meta = {}
                setattr(tool_obj, "meta", meta)
            except Exception:
                meta = None

    existing_schema = _normalize_input_schema(tool_obj)
    if not isinstance(existing_schema, Mapping):
        try:
            setattr(tool_obj, "input_schema", schema)
            # Some clients/framework versions prefer camelCase.
            try:
                setattr(tool_obj, "inputSchema", schema)
            except Exception:
                pass
        except Exception:
            meta = getattr(tool_obj, "meta", None)
            if isinstance(meta, dict):
                meta.setdefault("input_schema", schema)
                # Keep a camelCase alias for downstream UIs that follow MCP's
                # `inputSchema` convention.
                meta.setdefault("inputSchema", schema)

    # Best-effort: attach visibility to tool metadata so UIs that only inspect
    # the registered tool object (and not the wrapper function) can still render
    # it. Visibility remains non-authoritative (the wrapper enforces behavior).
    try:
        setattr(tool_obj, "__mcp_visibility__", str(visibility))
    except Exception:
        if isinstance(meta, dict):
            meta.setdefault("visibility", str(visibility))

    if isinstance(meta, dict) and isinstance(ui, Mapping) and ui:
        meta["ui"] = dict(ui)

    if tags:
        tag_list = [str(t) for t in tags if t is not None and str(t).strip()]
        if tag_list:
            if isinstance(meta, dict):
                meta["tags"] = tag_list


def _attach_tool_annotations(tool_obj: Any, annotations: Mapping[str, Any]) -> None:
    """Attach annotations onto the registered tool object.

    FastMCP variants and unit tests sometimes represent a tool object as a plain
    dict. UIs typically look for either an `.annotations` attribute or an
    `annotations` key.
    """

    if tool_obj is None:
        return
    if not isinstance(annotations, Mapping):
        return

    ann = dict(annotations)

    # Object attribute (preferred)
    try:
        setattr(tool_obj, "annotations", ann)
        return
    except Exception:
        pass

    # Mapping style (used by tests / some stubs)
    try:
        if isinstance(tool_obj, Mapping):
            try:
                tool_obj["annotations"] = ann  # type: ignore[index]
            except Exception:
                pass
    except Exception:
        pass

    # As a final fallback, stash under meta.
    meta = getattr(tool_obj, "meta", None)
    if isinstance(meta, dict):
        meta.setdefault("annotations", ann)


def _tool_annotations(
    *,
    write_action: bool,
    open_world_hint: Optional[bool] = None,
    destructive_hint: Optional[bool] = None,
    read_only_hint: Optional[bool] = None,
) -> dict[str, Any]:
    """Return MCP-style tool annotations used by UIs.

    ChatGPT and other MCP clients commonly read these booleans to render badges
    like READ/WRITE, OPEN WORLD, and DESTRUCTIVE.
    """

    # Defaults
    if read_only_hint is None:
        read_only_hint = not bool(write_action)
    if destructive_hint is None:
        destructive_hint = bool(write_action)
    if open_world_hint is None:
        # Tools represent actions that interact with something outside the model
        # (filesystem/network/hosted provider). Default to True.
        open_world_hint = True

    return {
        "readOnlyHint": bool(read_only_hint),
        "destructiveHint": bool(destructive_hint),
        "openWorldHint": bool(open_world_hint),
    }


def _schema_summary(schema: Mapping[str, Any], *, max_fields: int = 8) -> str:
    """Create a compact, UI-friendly parameter summary from a JSON schema."""

    try:
        props = schema.get("properties")
        if not isinstance(props, Mapping):
            return ""
        required = schema.get("required")
        req = set(required) if isinstance(required, list) else set()
        items: list[str] = []
        for name in sorted(props.keys()):
            if len(items) >= max_fields:
                break
            spec = props.get(name)
            if not isinstance(spec, Mapping):
                items.append(str(name))
                continue
            typ = spec.get("type")
            if isinstance(typ, list):
                typ_s = "|".join(str(t) for t in typ)
            elif isinstance(typ, str):
                typ_s = typ
            else:
                typ_s = str(spec.get("format") or "any")
            default = spec.get("default")
            d = ""
            if default is not None:
                d = f"={_truncate_text(default, limit=24)}"
            req_mark = "*" if name in req else ""
            items.append(f"{name}{req_mark}:{typ_s}{d}")
        extra = len(props) - len(items)
        tail = f", +{extra} more" if extra > 0 else ""
        return ", ".join(items) + tail
    except Exception:
        return ""


def _invocation_messages(
    tool_name: str,
    *,
    ui: Optional[Mapping[str, Any]] = None,
) -> tuple[str, str]:
    """Compute default 'invoking' and 'invoked' messages for a tool."""

    label = None
    if isinstance(ui, Mapping):
        label = ui.get("label")
    if not label:
        label = tool_name.replace("_", " ").strip().title()
    invoking = f"Invoking {label}…"
    invoked = f"Invoked {label}."
    return invoking, invoked


def _tool_write_allowed(write_action: bool) -> bool:
    # Used for metadata/introspection.
    del write_action
    return bool(WRITE_ALLOWED)


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

    This function is intentionally a no-op for compatibility.
    """
    del tool_name, write_action
    return


# -----------------------------------------------------------------------------
# Compatibility: dedupe helpers used by tests
# -----------------------------------------------------------------------------

# Async dedupe cache is scoped per loop so futures/tasks are never shared across loops.
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

    This function exists to prevent duplicate tool executions when the upstream
    client retries an identical call (common during long-running workflows).

    Semantics:
    - First call creates a Task and runs work.
    - Subsequent calls while the Task is still running await the same Task.
    - Successful results are cached for ttl_s seconds after completion.
    - Failures are not cached; the cache entry is removed on completion.

    Important: if an awaiting caller is cancelled (e.g. upstream disconnect), we
    propagate asyncio.CancelledError to that caller but we do NOT cancel the
    shared Task. A later retry with the same dedupe key can await the in-flight
    work instead of restarting mid-workflow.
    """
    ttl_s = max(0.0, float(ttl_s))
    now = time.time()

    loop = asyncio.get_running_loop()
    lid = _loop_id(loop)
    cache_key = (lid, dedupe_key)
    lock = _get_async_lock(loop)

    async with lock:
        # Opportunistic cleanup for this loop.
        # Only expire entries whose underlying work is done.
        expired = [
            k
            for k, (exp, fut) in _DEDUPE_ASYNC_CACHE.items()
            if k[0] == lid and exp < now and getattr(fut, "done", lambda: True)()
        ]
        for k in expired:
            _DEDUPE_ASYNC_CACHE.pop(k, None)

        item = _DEDUPE_ASYNC_CACHE.get(cache_key)
        if item is not None:
            expires_at, fut = item
            try:
                if fut.cancelled():
                    _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
                elif not fut.done():
                    # Shield prevents request cancellation from cancelling the shared task.
                    return await asyncio.shield(fut)
                elif expires_at >= now:
                    return await fut
                else:
                    _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
            except Exception:
                # If the cached future is in an unexpected state, drop it and recompute.
                _DEDUPE_ASYNC_CACHE.pop(cache_key, None)

        aw = work() if callable(work) else work
        fut = asyncio.create_task(aw)
        # Temporary expiry until we know completion time.
        _DEDUPE_ASYNC_CACHE[cache_key] = (now + ttl_s, fut)

        # Finalize caching/cleanup once the task completes.
        def _finalize_done(task: asyncio.Future) -> None:
            async def _finalize_async() -> None:
                completed_at = time.time()
                async with lock:
                    cur = _DEDUPE_ASYNC_CACHE.get(cache_key)
                    if not cur or cur[1] is not task:
                        return
                    if task.cancelled():
                        _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
                        return
                    try:
                        exc = task.exception()
                    except Exception:
                        exc = Exception("Failed to resolve task exception")
                    if exc is not None:
                        # Failures are not cached.
                        _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
                        return
                    # Success: extend expiry from completion so retries can reuse the result.
                    _DEDUPE_ASYNC_CACHE[cache_key] = (completed_at + ttl_s, task)

            try:
                loop.create_task(_finalize_async())
            except Exception:
                # Best-effort; if scheduling fails (e.g. loop closing), do nothing.
                return

        try:
            fut.add_done_callback(_finalize_done)
        except Exception:
            pass

    # Await the shared task. If the caller is cancelled (e.g. upstream disconnect),
    # the Task continues running due to shielding; a retry can await it later.
    return await asyncio.shield(fut)


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


def _strip_internal_log_fields(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Remove internal log-only keys from a tool result before returning.

    Tool implementations may include keys prefixed with ``__log_`` to pass
    additional context to provider logs (e.g., precomputed diffs).
    These keys are filtered from client responses.
    """

    if not isinstance(payload, Mapping):
        return dict(payload)
    out = dict(payload)
    for k in list(out.keys()):
        if isinstance(k, str) and k.startswith("__log_"):
            out.pop(k, None)
    return out


def _tool_result_outcome(result: Any) -> str:
    """Classify a tool return payload as ok/warning/error.

    Tools historically used both raised exceptions and structured error dicts.
    This helper ensures we do not log structured errors as successful tool calls.
    """

    if not isinstance(result, Mapping):
        return "ok"

    status = str(result.get("status") or "").strip().lower()
    ok_val = result.get("ok")
    if isinstance(ok_val, bool) and ok_val is False:
        return "error"
    if status in {"error", "failed", "failure"}:
        return "error"

    # Some tool results (notably terminal-style tools) indicate failure via
    # process outcomes rather than explicit status/error fields.
    exit_code = result.get("exit_code")
    timed_out = result.get("timed_out")
    if isinstance(exit_code, int) and exit_code != 0:
        return "error"
    if timed_out is True:
        return "error"

    # Some results wrap a nested result payload under "result".
    nested = result.get("result")
    if isinstance(nested, Mapping):
        n_exit = nested.get("exit_code")
        n_timeout = nested.get("timed_out")
        if isinstance(n_exit, int) and n_exit != 0:
            return "error"
        if n_timeout is True:
            return "error"

    err = result.get("error")
    if isinstance(err, str) and err.strip():
        return "error"
    if isinstance(err, Mapping) and (err.get("message") or err.get("detail")):
        return "error"

    if status in {"warning", "warn", "passed_with_warnings", "cancelled", "canceled"}:
        return "warning"
    warnings = result.get("warnings")
    if isinstance(warnings, list) and any(bool(str(w).strip()) for w in warnings):
        return "warning"
    if isinstance(warnings, str) and warnings.strip():
        return "warning"

    return "ok"


def _normalize_tool_result_envelope(result: Any) -> Any:
    """Normalize tool results to a consistent ok/status/warnings surface.

    - Mapping results are augmented in-place (copied) with ok/status fields.
    - Scalar/list results are returned unchanged unless TOOL_RESULT_ENVELOPE_SCALARS is enabled.
    """
    if _running_under_pytest():
        return result

    if not TOOL_RESULT_ENVELOPE:
        return result

    # Preserve non-mapping results for compatibility.
    if not isinstance(result, Mapping):
        if TOOL_RESULT_ENVELOPE_SCALARS:
            return {"status": "success", "ok": True, "result": result}
        return result

    out: dict[str, Any] = dict(result)
    outcome = _tool_result_outcome(out)

    raw_status = out.get("status")
    raw_status_str = str(raw_status).strip() if raw_status is not None else ""

    if outcome == "error":
        out["status"] = "error"
        out["ok"] = False
        # Ensure a top-level error message when possible.
        if not (isinstance(out.get("error"), str) and str(out.get("error")).strip()):
            err_detail = out.get("error_detail")
            if isinstance(err_detail, Mapping):
                msg = err_detail.get("message") or err_detail.get("error")
                if isinstance(msg, str) and msg.strip():
                    out["error"] = msg.strip()
        return out

    if outcome == "warning":
        # Preserve the original status string when it conveys more nuance.
        if raw_status_str and raw_status_str.lower() not in {"warning", "warn"}:
            out.setdefault("status_raw", raw_status_str)
        out["status"] = "warning"
        out.setdefault("ok", True)

        warnings = out.get("warnings")
        if isinstance(warnings, str):
            cleaned = warnings.strip()
            out["warnings"] = [cleaned] if cleaned else []
        elif isinstance(warnings, list):
            cleaned_list: list[str] = []
            for w in warnings:
                if w is None:
                    continue
                s = str(w).strip()
                if s:
                    cleaned_list.append(s)
            out["warnings"] = cleaned_list
        elif warnings is None:
            out["warnings"] = []
        else:
            out["warnings"] = [str(warnings).strip()] if str(warnings).strip() else []

        return out

    # Success
    out.setdefault("ok", True)
    if not raw_status_str:
        out["status"] = "success"
    elif raw_status_str.lower() in {"ok", "success", "succeeded", "passed"}:
        out["status"] = "success"
    # Otherwise, preserve the original status value.
    return out


def _chatgpt_friendly_result(result: Any, *, req: Mapping[str, Any] | None = None) -> Any:
    """Return a ChatGPT-friendly version of a tool result.

    This is opt-in via GITHUB_MCP_RESPONSE_MODE=chatgpt.

    Goals:
    - consistent ok/status surface
    - include a compact summary to aid LLM planning
    """

    mode = _effective_response_mode(req)
    if mode not in {"chatgpt", "compact"}:
        return result

    try:
        # Scalars/lists: wrap so callers always get a mapping with status.
        if not isinstance(result, Mapping):
            return _inject_adaptiv_mcp_metadata(
                {
                    "status": "success",
                    "ok": True,
                    "result": result,
                    "summary": _result_snapshot(result),
                }
            )

        out: dict[str, Any] = _inject_adaptiv_mcp_metadata(result)

        # Ensure stable status/ok.
        outcome = _tool_result_outcome(out)
        if "ok" not in out:
            out["ok"] = outcome != "error"
        status = out.get("status")
        status_str = str(status).strip().lower() if status is not None else ""
        if not status_str or status_str in {"ok", "passed", "succeeded", "success"}:
            out["status"] = (
                "success" if outcome == "ok" else ("warning" if outcome == "warning" else "error")
            )
        elif status_str in {"warn", "warning"}:
            out["status"] = "warning"
        elif status_str in {"error", "failed", "failure"}:
            out["status"] = "error"

        # Add a compact snapshot for LLMs (does not replace the full payload).
        out.setdefault("summary", _result_snapshot(out))

        # Surface stdout/stderr in ChatGPT-friendly payloads.
        try:
            _inject_stdout_stderr(out)
        except Exception:
            pass

        truncated_fields: list[str] = []

        # Truncate common large lists to keep payload sizes manageable.
        for key in ("packages", "checks", "results", "items"):
            val = out.get(key)
            if (
                isinstance(val, list)
                and CHATGPT_RESPONSE_MAX_LIST_ITEMS > 0
                and len(val) > CHATGPT_RESPONSE_MAX_LIST_ITEMS
            ):
                out[f"{key}_total"] = len(val)
                out[key] = val[:CHATGPT_RESPONSE_MAX_LIST_ITEMS]
                out[f"{key}_truncated"] = True
                truncated_fields.append(key)

        if truncated_fields:
            out.setdefault("truncated_fields", sorted(set(truncated_fields)))

        return out
    except Exception as exc:
        # Best-effort: never break tool behavior if the shaper fails.
        # However, failures here are otherwise invisible and can look like
        # "errors being swallowed" to operators and clients.
        try:
            LOGGER.warning(
                "Tool result shaping failed; returning raw result",
                extra={
                    "event": "tool_result_shape_failed",
                    "error_type": exc.__class__.__name__,
                    "error_message": _truncate_text(str(exc), limit=200) if str(exc) else None,
                },
                exc_info=exc if LOG_TOOL_EXC_INFO else None,
            )
        except Exception:
            pass
        return result


def _log_tool_warning(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    duration_ms: float,
    result: Any,
    all_args: Mapping[str, Any] | None = None,
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
    if all_args is not None:
        payload.update(_extract_context(all_args))
    payload["duration_ms"] = duration_ms
    payload["response"] = _result_snapshot(result) if not LOG_TOOL_PAYLOADS else result

    if not HUMAN_LOGS:
        LOGGER.warning(
            f"{_ansi('!', ANSI_YELLOW)} {_ansi(tool_name, ANSI_CYAN)} ms={duration_ms:.2f}",
            extra={"event": "tool_call_completed_with_warnings", **payload},
        )
        return

    friendly = _friendly_tool_name(tool_name)
    bits = _friendly_arg_bits(all_args or {})
    suffix = (" - " + " - ".join(bits)) if bits else ""
    prefix = _ansi("RES", ANSI_YELLOW) + " " + _ansi(friendly, ANSI_CYAN)
    ms = _ansi(f"({duration_ms:.0f}ms)", ANSI_DIM)
    snap = payload.get("response") if not LOG_TOOL_PAYLOADS else _result_snapshot(result)
    rbits = _friendly_result_bits(snap if isinstance(snap, Mapping) else None)
    res_suffix = (" - " + " - ".join(rbits)) if rbits else ""
    msg = f"{prefix} {ms}{suffix}{res_suffix}"
    if LOG_TOOL_LOG_IDS:
        msg = msg + " " + _ansi(f"[{shorten_token(call_id)}]", ANSI_DIM)
    inline = payload.get("log_context")
    if isinstance(inline, str) and inline:
        msg = msg + " " + _ansi(inline, ANSI_DIM)
    LOGGER.warning(msg, extra={"event": "tool_call_completed_with_warnings", **payload})


def _log_tool_returned_error(
    *,
    tool_name: str,
    call_id: str,
    write_action: bool,
    req: Mapping[str, Any],
    schema_hash: Optional[str],
    schema_present: bool,
    duration_ms: float,
    result: Mapping[str, Any],
    all_args: Mapping[str, Any],
) -> None:
    """Log a tool call that returned an error payload without raising."""

    payload = _tool_log_payload(
        tool_name=tool_name,
        call_id=call_id,
        write_action=write_action,
        req=req,
        schema_hash=schema_hash,
        schema_present=schema_present,
        all_args=all_args,
    )
    payload.update({"duration_ms": duration_ms, "phase": "execute", "error_type": "ReturnedError"})

    err = result.get("error")
    if isinstance(err, Mapping):
        payload["error_message"] = err.get("message")
    elif isinstance(err, str):
        payload["error_message"] = err

    payload["response"] = result if LOG_TOOL_PAYLOADS else _result_snapshot(result)

    arg_summary = _args_summary(all_args)
    kv_map: dict[str, Any] = {
        "phase": "execute",
        "ms": f"{duration_ms:.2f}",
        **{k: v for k, v in arg_summary.items()},
    }
    err_msg = payload.get("error_message")
    if isinstance(err_msg, str) and err_msg.strip():
        kv_map["error"] = _truncate_text(err_msg, limit=140)
    snap = payload.get("response")
    if isinstance(snap, Mapping):
        rbits = _friendly_result_bits(snap)
        if rbits:
            kv_map["response"] = "; ".join(rbits[:3])
    if LOG_TOOL_LOG_IDS:
        req_ctx = payload.get("request", {}) if isinstance(payload.get("request"), Mapping) else {}
        kv_map.update(
            {
                "call_id": payload.get("call_id"),
                "session_id": req_ctx.get("session_id"),
                "message_id": req_ctx.get("message_id"),
                "path": req_ctx.get("path"),
            }
        )
    line = _format_log_kv(kv_map)
    prefix = _ansi("RES", ANSI_RED) + " " + _ansi(_friendly_tool_name(tool_name), ANSI_CYAN)
    msg = f"{prefix} {line}"
    inline = payload.get("log_context")
    if isinstance(inline, str) and inline:
        msg = msg + " " + _ansi(inline, ANSI_DIM)
    LOGGER.error(msg, extra={"event": "tool_call_failed", **payload})


def _extract_tool_meta(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract the optional _meta payload without mutating kwargs."""

    if not kwargs:
        return {}
    meta = kwargs.get("_meta")
    if isinstance(meta, Mapping):
        return dict(meta)
    return {}


def _dedupe_ttl_seconds(*, write_action: bool, meta: Mapping[str, Any]) -> float:
    """Determine the in-request idempotency TTL.

    This is intentionally scoped to inbound MCP/HTTP requests (see
    _should_enforce_write_gate). It prevents accidental duplicate execution
    when the client/agent repeats an identical tool call.
    """

    # Allow callers to opt out per call.
    if meta.get("dedupe") is False:
        return 0.0

    # Optional per-call override.
    override = meta.get("dedupe_ttl_s")
    if override is None:
        override = meta.get("dedupe_ttl_seconds")
    if isinstance(override, (int, float)):
        return max(0.0, float(override))

    # Environment defaults.
    #
    # Reliability note:
    # Long workflows frequently involve transient transport failures. Dedupe is
    # our primary protection against accidentally re-executing a tool after a
    # retry. Historically the default TTL was 0 (disabled), which made retries
    # much more likely to double-execute.
    #
    # New behavior:
    # - If the env var is UNSET, we use conservative defaults.
    # - If the env var is SET (including to "0"), we honor it exactly.
    env_name = (
        "GITHUB_MCP_TOOL_DEDUPE_TTL_WRITE_S"
        if write_action
        else "GITHUB_MCP_TOOL_DEDUPE_TTL_READ_S"
    )
    raw = os.environ.get(env_name)

    if raw is None:
        # Defaults tuned for typical agent retry windows.
        # Reads: short window to coalesce repeated polling and transient retries.
        # Writes: longer window because downstream providers can take longer and
        # retries are more dangerous.
        return 300.0 if write_action else 30.0

    try:
        return max(0.0, float(str(raw).strip()))
    except Exception:
        # If misconfigured, fall back to safe defaults.
        return 300.0 if write_action else 30.0


def _dedupe_key(
    *, tool_name: str, write_action: bool, req: Mapping[str, Any], args: Mapping[str, Any]
) -> str:
    """Build a stable idempotency key for a tool call."""

    # Scope to the *turn* identity where possible so independent sessions do
    # not share cached results, while client retries of the same turn can be
    # safely deduped.
    request_id = req.get("request_id")
    session_id = req.get("session_id")
    message_id = req.get("message_id")
    path = req.get("path")

    # Prefer a stable idempotency key (if the client provides one), then the
    # (session_id, message_id) pair.
    #
    # request_id is commonly regenerated on retries. Including it when a more
    # stable scope exists can reduce dedupe effectiveness.
    explicit_idempotency_key = req.get("idempotency_key") or req.get("dedupe_key")
    if explicit_idempotency_key:
        scope = f"i:{explicit_idempotency_key}"
    else:
        scope_parts: list[str] = []
        if session_id:
            scope_parts.append(f"s:{session_id}")
        if message_id:
            scope_parts.append(f"m:{message_id}")
        if not scope_parts:
            # Fall back to request_id only when no better scope exists.
            if request_id:
                scope_parts.append(f"r:{request_id}")
            elif path:
                scope_parts.append(f"p:{path}")
            else:
                scope_parts.append("global")
        scope = ",".join(scope_parts)

    try:
        args_json = json.dumps(
            args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
    except Exception:
        args_json = str(dict(args))

    digest = hashlib.sha256(args_json.encode("utf-8", errors="replace")).hexdigest()
    return "|".join(
        [
            str(tool_name),
            "write" if write_action else "read",
            scope,
            digest,
        ]
    )


def _extract_context(all_args: Mapping[str, Any]) -> dict[str, Any]:
    # Keep context small by default.
    if not isinstance(all_args, Mapping) or not all_args:
        return {}
    if LOG_TOOL_PAYLOADS:
        # Preserve full args without truncation; ensure JSON-serializable.
        try:
            from github_mcp.mcp_server.schemas import _preflight_tool_args

            preflight = _preflight_tool_args("<tool>", all_args, compact=False)
            args = preflight.get("args") if isinstance(preflight, Mapping) else dict(all_args)
        except Exception:
            args = dict(all_args)
        return {"tool_args": args}

    # Default: compact snapshot.
    return {"tool_args": _args_summary(all_args)}


def _result_snapshot(result: Any) -> dict[str, Any]:
    """Produce a compact result summary for provider logs."""

    # Scalars
    if result is None:
        return {"type": "null"}
    if isinstance(result, (bool, int, float, str)):
        return {"type": type(result).__name__, "value": _truncate_text(result, limit=180)}

    # Collections
    if isinstance(result, list):
        return {
            "type": "list",
            "len": len(result),
            "head": [_truncate_text(v, limit=140) for v in result[:3]],
        }

    if isinstance(result, Mapping):
        # Prefer common "status" and "error" surfaces.
        out: dict[str, Any] = {
            "type": "dict",
            "keys": len(result),
        }

        # Common runtime fields
        for key in (
            "status",
            "state",
            "ok",
            "success",
            "url",
            "html_url",
            "number",
            "id",
            "name",
            "full_name",
        ):
            if key in result and result.get(key) not in (None, ""):
                out[key] = _truncate_text(result.get(key), limit=180)

        # Structured tool error shape
        err = result.get("error")
        if isinstance(err, Mapping) and err.get("message"):
            out["error"] = _truncate_text(err.get("message"), limit=220)
        elif isinstance(err, str) and err.strip():
            out["error"] = _truncate_text(err, limit=220)

        # terminal_command convenience: capture exit code
        inner = result.get("result")
        if isinstance(inner, Mapping) and inner.get("exit_code") is not None:
            out["exit_code"] = inner.get("exit_code")
        return out

    return {"type": type(result).__name__, "value": _truncate_text(result, limit=180)}


def _friendly_result_bits(snapshot: Mapping[str, Any] | None) -> list[str]:
    """Convert a result snapshot into short, user-facing bits for RES lines."""

    if not isinstance(snapshot, Mapping) or not snapshot:
        return []

    typ = snapshot.get("type")
    bits: list[str] = []

    if typ == "dict":
        # Preferred high-signal fields.
        for k in ("exit_code", "status", "state", "ok", "success", "number", "name", "full_name"):
            if k in snapshot and snapshot.get(k) not in (None, ""):
                bits.append(f"{k}={_truncate_text(snapshot.get(k), limit=60)}")

        # URLs are helpful but can be long.
        for k in ("html_url", "url"):
            if k in snapshot and snapshot.get(k) not in (None, ""):
                bits.append(f"{k}={_truncate_text(snapshot.get(k), limit=80)}")
                break

        err = snapshot.get("error")
        if isinstance(err, str) and err.strip():
            bits.append(f"error={_truncate_text(err, limit=120)}")

        if not bits and snapshot.get("keys") is not None:
            bits.append(f"keys={snapshot.get('keys')}")
        return bits

    if typ == "list":
        if snapshot.get("len") is not None:
            bits.append(f"len={snapshot.get('len')}")
        return bits

    # Scalar-ish
    val = snapshot.get("value")
    if val not in (None, ""):
        bits.append(f"value={_truncate_text(val, limit=120)}")
    return bits


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
    inline = _inline_context(req)
    payload: dict[str, Any] = {
        "tool": tool_name,
        "call_id": shorten_token(call_id),
        "request": snapshot_request_context(req),
        "log_context": inline or None,
    }
    if write_action:
        payload["write_action"] = True
    if LOG_TOOL_VERBOSE_EXTRAS:
        payload["schema_present"] = bool(schema_present)
        payload["schema_hash"] = shorten_token(schema_hash) if schema_present else None
    if all_args is not None:
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
    # Snapshot mode emits both request and response lines.
    if not LOG_TOOL_CALLS or not (LOG_TOOL_SNAPSHOTS or LOG_TOOL_CALL_STARTS):
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
    # Developer-facing, scan-friendly request snapshot.
    friendly = _friendly_tool_name(tool_name)
    bits = _friendly_arg_bits(all_args)
    suffix = (" - " + " - ".join(bits)) if bits else ""
    prefix = _ansi("REQ", ANSI_GREEN) + " " + _ansi(friendly, ANSI_CYAN)
    msg = f"{prefix}{suffix}"
    if LOG_TOOL_LOG_IDS:
        msg = msg + " " + _ansi(f"[{shorten_token(call_id)}]", ANSI_DIM)
    inline = payload.get("log_context")
    if isinstance(inline, str) and inline:
        msg = msg + " " + _ansi(inline, ANSI_DIM)
    LOGGER.info(msg, extra={"event": "tool_call_started", **payload})


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
    all_args: Mapping[str, Any] | None = None,
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
    if all_args is not None:
        payload.update(_extract_context(all_args))
    payload["duration_ms"] = duration_ms
    if LOG_TOOL_PAYLOADS:
        try:
            from github_mcp.mcp_server.schemas import _jsonable

            payload["response"] = _jsonable(result)
        except Exception:
            payload["response"] = result
    else:
        payload["response"] = _result_snapshot(result)

    if HUMAN_LOGS:
        friendly = _friendly_tool_name(tool_name)
        bits = _friendly_arg_bits(all_args or {})
        suffix = (" - " + " - ".join(bits)) if bits else ""
        prefix = _ansi("RES", ANSI_GREEN) + " " + _ansi(friendly, ANSI_CYAN)
        ms = _ansi(f"({duration_ms:.0f}ms)", ANSI_DIM)
        snap = payload.get("response") if not LOG_TOOL_PAYLOADS else _result_snapshot(result)
        rbits = _friendly_result_bits(snap if isinstance(snap, Mapping) else None)
        res_suffix = (" - " + " - ".join(rbits)) if rbits else ""
        msg = f"{prefix} {ms}{suffix}{res_suffix}"
        if LOG_TOOL_LOG_IDS:
            msg = msg + " " + _ansi(f"[{shorten_token(call_id)}]", ANSI_DIM)
        inline = payload.get("log_context")
        if isinstance(inline, str) and inline:
            msg = msg + " " + _ansi(inline, ANSI_DIM)
        LOGGER.info(msg, extra={"event": "tool_call_completed", **payload})

        # Optional developer-facing visuals for common workflows.
        # These are emitted as a second log entry so dashboards can filter on
        # `event=tool_call_completed` vs `event=tool_visual`.
        try:
            if LOG_TOOL_VISUALS and all_args is not None:
                visual = ""
                kind = ""

                # 1) Diff / patch tools
                diff_candidate = None
                if isinstance(result, Mapping):
                    diff_candidate = (
                        result.get("__log_diff") or result.get("diff") or result.get("patch")
                    )
                if diff_candidate is None and isinstance(all_args, Mapping):
                    diff_candidate = all_args.get("diff") or all_args.get("patch")

                if isinstance(diff_candidate, str) and _looks_like_unified_diff(diff_candidate):
                    if LOG_TOOL_DIFF_SNIPPETS:
                        kind = "diff"
                        visual = _preview_unified_diff(diff_candidate)

                # 2) Workspace change listings (git status porcelain)
                if not visual and isinstance(result, Mapping):
                    status_lines = (
                        result.get("changed_files")
                        or result.get("staged_files")
                        or result.get("files")
                    )
                    if isinstance(status_lines, list) and all(
                        isinstance(x, str) for x in status_lines
                    ):
                        if _is_porcelain_status_list(status_lines):
                            kind = "changes"
                            visual = _preview_changed_files(status_lines)
                        else:
                            kind = "files"
                            visual = _preview_file_list(status_lines)

                # 2b) Search hits
                if not visual and isinstance(result, Mapping) and tool_name == "search_workspace":
                    hits = result.get("results")
                    if isinstance(hits, list):
                        kind = "search"
                        visual = _preview_search_hits(
                            [x for x in hits if isinstance(x, Mapping)]  # type: ignore[list-item]
                        )

                # 2c) Render endpoints
                if (
                    not visual
                    and isinstance(result, Mapping)
                    and (
                        tool_name.startswith("list_render_")
                        or tool_name.startswith("render_list_")
                        or tool_name.startswith("render_get_")
                        or tool_name.startswith("get_render_")
                    )
                ):
                    body = result.get("json") if "json" in result else result
                    items = _render_extract_list(body)
                    if isinstance(items, list):
                        kind = "render"
                        if tool_name.endswith("_logs"):
                            visual = _preview_render_logs(items)
                        else:
                            visual = _preview_json_objects(items, header="render")

                # 3) File reads (show which file + a snippet)
                if (
                    not visual
                    and LOG_TOOL_READ_SNIPPETS
                    and isinstance(result, Mapping)
                    and isinstance(result.get("path"), str)
                    and isinstance(result.get("text"), str)
                ):
                    start_line = 1
                    if isinstance(result.get("start_line"), int):
                        start_line = int(result.get("start_line"))
                    elif isinstance(result.get("__log_start_line"), int):
                        start_line = int(result.get("__log_start_line"))

                    # Only preview on read tools to avoid echoing writes unless explicitly enabled.
                    if not bool(write_action):
                        kind = "read"
                        visual = _preview_file_snippet(
                            str(result.get("path") or ""),
                            str(result.get("text") or ""),
                            start_line=start_line,
                        )

                # 4) terminal_command output preview (stdout/stderr)
                if not visual and isinstance(result, Mapping) and tool_name == "terminal_command":
                    kind = "terminal"
                    visual = _preview_terminal_result(result)

                if visual:
                    _log_tool_visual(
                        tool_name=tool_name,
                        call_id=call_id,
                        req=req,
                        kind=kind or "info",
                        visual=visual,
                    )
        except Exception as exc:
            # Visual logging is best-effort, but failures should be visible.
            try:
                LOGGER.debug("Visual logging failed", exc_info=exc)
            except Exception:
                pass
    else:
        kv_map: dict[str, Any] = {
            "tool": tool_name,
            "ms": f"{duration_ms:.2f}",
        }
        if LOG_TOOL_LOG_IDS:
            kv_map["call_id"] = shorten_token(call_id)
        line = _format_log_kv(kv_map)
        prefix = _ansi("✓", ANSI_GREEN) + " " + _ansi(tool_name, ANSI_CYAN)
        msg = f"{prefix} {line}"
        inline = payload.get("log_context")
        if isinstance(inline, str) and inline:
            msg = msg + " " + _ansi(inline, ANSI_DIM)
        LOGGER.info(msg, extra={"event": "tool_call_completed", **payload})


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

        # Include a compact response snapshot so failures have both sides.
        if LOG_TOOL_PAYLOADS:
            payload["response"] = structured_error
        else:
            payload["response"] = _result_snapshot(structured_error)

    call_id_short = payload.get("call_id")

    # Emit a scan-friendly message with a compact arg summary.
    req_ctx = payload.get("request", {}) if isinstance(payload.get("request"), Mapping) else {}
    msg_id = req_ctx.get("message_id")
    session_id = req_ctx.get("session_id")
    path = req_ctx.get("path")
    if isinstance(path, str) and path.startswith("/sse"):
        path = None

    arg_summary = _args_summary(all_args)
    kv_map: dict[str, Any] = {
        "phase": phase,
        "ms": f"{duration_ms:.2f}",
        **{k: v for k, v in arg_summary.items()},
    }
    err_msg = payload.get("error_message")
    if isinstance(err_msg, str) and err_msg.strip():
        kv_map["error"] = _truncate_text(err_msg, limit=140)
    snap = payload.get("response")
    if isinstance(snap, Mapping):
        rbits = _friendly_result_bits(snap)
        if rbits:
            kv_map["response"] = "; ".join(rbits[:3])
    if LOG_TOOL_LOG_IDS:
        kv_map.update(
            {
                "call_id": call_id_short,
                "session_id": session_id,
                "message_id": msg_id,
                "path": path,
            }
        )
    line = _format_log_kv(kv_map)
    prefix = _ansi("RES", ANSI_RED) + " " + _ansi(_friendly_tool_name(tool_name), ANSI_CYAN)
    msg = f"{prefix} {line}"
    inline = payload.get("log_context")
    if isinstance(inline, str) and inline:
        msg = msg + " " + _ansi(inline, ANSI_DIM)
    LOGGER.error(
        msg,
        extra={"event": "tool_call_failed", **payload},
        # Hosted providers (Render) can become unusably noisy when every failure
        # includes a full traceback. Emit `exc_info` only when explicitly enabled.
        exc_info=exc if LOG_TOOL_EXC_INFO else None,
    )

    # NOTE: we intentionally emit a single provider log line per failure.


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
    all_args: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    structured_error = _structured_tool_error(
        exc,
        context=tool_name,
        path=None,
        request=dict(req) if isinstance(req, Mapping) else None,
        trace={"phase": phase, "call_id": shorten_token(call_id)},
        args=dict(all_args) if isinstance(all_args, Mapping) else None,
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
    tags: Optional[Iterable[str]] = None,
    annotations: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Register a tool with FastMCP across signature variants.

    FastMCP has had multiple API shapes over time ("factory" vs "direct" tool
    registration). This helper attempts registration in a compatibility order
    while avoiding the common failure:

      TypeError: FastMCP.tool() got multiple values for argument 'name'

    Notes for developers:
      - When FastMCP is not installed, we register a lightweight stub tool so
        HTTP routes and introspection can still function.

    """
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
        if isinstance(annotations, Mapping):
            try:
                tool_obj.annotations = dict(annotations)
            except Exception:
                pass
        _REGISTERED_MCP_TOOLS[:] = [
            (t, f) for (t, f) in _REGISTERED_MCP_TOOLS if _registered_tool_name(t, f) != name
        ]
        _REGISTERED_MCP_TOOLS.append((tool_obj, fn))
        return tool_obj

    params = _fastmcp_tool_params()
    style = _fastmcp_call_style(params)

    # Build kwargs in descending compatibility order.

    base: dict[str, Any] = {"name": name, "description": description}
    base_with_meta: dict[str, Any] = {
        "name": name,
        "description": description,
        "meta": {},
    }
    if isinstance(annotations, Mapping) and annotations:
        base_with_meta["annotations"] = dict(annotations)
    if tags:
        tag_list = [str(t) for t in tags if t is not None and str(t).strip()]
        if tag_list:
            base_with_meta["meta"]["tags"] = tag_list
    attempts = [base_with_meta, base, {"name": name}]

    last_exc: Optional[Exception] = None
    tool_obj: Any = None

    for kw in attempts:
        kw2 = _filter_kwargs_for_signature(params, dict(kw))

        # Factory style: mcp.tool(**kw)(fn)
        if style in {"factory", "unknown"}:
            try:
                decorator = mcp.tool(**kw2)
                # FastMCP variants sometimes return a callable decorator object that already
                # has `.name` (and other metadata). In that case we STILL need to invoke it
                # with `fn` to actually register the tool.
                if callable(decorator):
                    try:
                        tool_obj = decorator(fn)
                    except TypeError:
                        # If it is not a decorator factory, treat it as an already-registered tool.
                        tool_obj = decorator
                else:
                    tool_obj = decorator
                break
            except TypeError as exc:
                last_exc = exc
                # If factory failed, and signature indicates direct style, try direct below.
                if style == "factory":
                    continue

        # Direct style: mcp.tool(fn, **kw)
        if style in {"direct", "unknown"}:
            # Skip direct style when signature starts with name.
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
        (t, f) for (t, f) in _REGISTERED_MCP_TOOLS if _registered_tool_name(t, f) != name
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
    write_action_resolver: Optional[Callable[[Mapping[str, Any]], bool]] = None,
    open_world_hint: Optional[bool] = None,
    destructive_hint: Optional[bool] = None,
    read_only_hint: Optional[bool] = None,
    ui: Optional[Mapping[str, Any]] = None,
    show_schema_in_description: bool = True,
    tags: Optional[Iterable[str]] = None,
    description: str | None = None,
    visibility: str = "public",  # accepted, ignored
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a callable as an MCP tool.

    Args:
      name: Optional override for the tool name (defaults to function __name__).
      write_action: Whether the tool performs mutations (e.g., git push, PR creation).
      description: Optional description (defaults to func.__doc__).
      visibility: Accepted for compatibility; reported via introspection.
      tags: Optional metadata labels reported via introspection.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")
        annotations = _tool_annotations(
            write_action=bool(write_action),
            open_world_hint=open_world_hint,
            destructive_hint=destructive_hint,
            read_only_hint=read_only_hint,
        )

        ui_meta = {}
        if isinstance(ui, Mapping) and ui:
            try:
                ui_meta.update(dict(ui))
            except Exception:
                pass
        if not ui_meta:
            # Heuristic defaults for better tool discoverability in MCP clients.
            # Individual tools can override via the `ui=` decorator argument.
            group = "github"
            icon = "🔧"
            if tool_name.startswith("render_"):
                group, icon = "render", "🟦"
            elif tool_name in {"terminal_command", "run_python", "apply_patch", "apply_workspace_operations"}:
                group, icon = "workspace", "🧩"
            elif tool_name.startswith("workspace_"):
                group, icon = "workspace", "🧩"
            elif tool_name.startswith("list_") or tool_name.startswith("get_"):
                group, icon = "github", "📖"
            ui_meta = {
                "group": group,
                "icon": icon,
                "label": tool_name.replace("_", " ").strip().title(),
            }

        invoking_msg, invoked_msg = _invocation_messages(tool_name, ui=ui_meta)
        ui_meta.setdefault("invoking", invoking_msg)
        ui_meta.setdefault("invoked", invoked_msg)
        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(
            func, signature, llm_level=llm_level
        )
        tag_list = [str(t) for t in (tags or []) if t is not None and str(t).strip()]

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                meta = _extract_tool_meta(kwargs)
                clean_kwargs = _strip_tool_meta(kwargs)
                all_args = _bind_call_args(signature, args, clean_kwargs) if LOG_TOOL_CALLS else {}
                req = get_request_context()
                start = time.perf_counter()

                effective_write_action = bool(write_action)
                if callable(write_action_resolver):
                    try:
                        # Prefer bound args if available; otherwise use raw kwargs.
                        basis = all_args if isinstance(all_args, Mapping) and all_args else clean_kwargs
                        effective_write_action = bool(write_action_resolver(basis))
                    except Exception:
                        # Best-effort; preserve base classification.
                        effective_write_action = bool(write_action)

                schema = getattr(wrapper, "__mcp_input_schema__", None)
                schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
                schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
                _log_tool_start(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    all_args=all_args,
                )
                try:
                    if _should_enforce_write_gate(req):
                        _enforce_write_allowed(tool_name, write_action=effective_write_action)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    structured_error = _emit_tool_error(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
                        start=start,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        req=req,
                        exc=exc,
                        phase="preflight",
                        all_args=all_args,
                    )
                    _log_tool_failure(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
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
                    # Best-effort idempotency for inbound requests. This prevents
                    # accidental duplicate execution when an agent repeats the same
                    # tool call (common when model-side planning loops happen).
                    result: Any
                    if _should_enforce_write_gate(req):
                        ttl_s = _dedupe_ttl_seconds(
                            write_action=bool(effective_write_action), meta=meta
                        )
                        if ttl_s > 0:
                            # Include all bound args for the key (positional + kwargs).
                            key_args = (
                                _bind_call_args(signature, args, clean_kwargs)
                                if signature is not None
                                else dict(clean_kwargs)
                            )
                            dedupe_key = _dedupe_key(
                                tool_name=tool_name,
                                write_action=bool(effective_write_action),
                                req=req,
                                args=key_args,
                            )
                            result = await _maybe_dedupe_call(
                                dedupe_key, lambda: func(*args, **clean_kwargs), ttl_s=ttl_s
                            )
                        else:
                            result = await func(*args, **clean_kwargs)
                    else:
                        result = await func(*args, **clean_kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    structured_error = _emit_tool_error(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
                        start=start,
                        schema_hash=schema_hash,
                        schema_present=True,
                        req=req,
                        exc=exc,
                        phase="execute",
                        all_args=all_args,
                    )
                    _log_tool_failure(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
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
                outcome = _tool_result_outcome(result)
                if outcome == "error" and isinstance(result, Mapping):
                    _log_tool_returned_error(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
                        req=req,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        duration_ms=duration_ms,
                        result=result,
                        all_args=all_args,
                    )
                elif outcome == "warning":
                    _log_tool_warning(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
                        req=req,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        duration_ms=duration_ms,
                        result=result,
                        all_args=all_args,
                    )
                else:
                    _log_tool_success(
                        tool_name=tool_name,
                        call_id=call_id,
                        write_action=effective_write_action,
                        req=req,
                        schema_hash=schema_hash if schema_present else None,
                        schema_present=schema_present,
                        duration_ms=duration_ms,
                        result=result,
                        all_args=all_args,
                    )
                # Return payload (client-facing). Keep logs based on the raw result.
                client_payload: Any
                if isinstance(result, Mapping):
                    client_payload = _strip_internal_log_fields(result)
                    # Include invocation-level metadata when classification is dynamic.
                    if callable(write_action_resolver):
                        try:
                            client_payload = dict(client_payload)
                            client_payload.setdefault(
                                "tool_metadata",
                                {
                                    "base_write_action": bool(write_action),
                                    "effective_write_action": bool(effective_write_action),
                                },
                            )
                        except Exception:
                            pass
                else:
                    client_payload = result
                if REDACT_TOOL_OUTPUTS and _effective_response_mode(req) in {"chatgpt", "compact"}:
                    try:
                        client_payload = redact_any(client_payload)
                    except Exception:
                        # Best-effort: never break tool behavior.
                        pass
                return _chatgpt_friendly_result(client_payload, req=req)

            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                description=normalized_description,
                tags=tag_list,
                annotations=annotations,
            )

            schema = _normalize_input_schema(wrapper.__mcp_tool__)
            if not isinstance(schema, Mapping):
                schema = _schema_from_signature(signature, tool_name=tool_name)
            if not isinstance(schema, Mapping):
                raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
            wrapper.__mcp_input_schema__ = schema
            wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
            wrapper.__mcp_tool_name__ = tool_name
            wrapper.__mcp_write_action__ = bool(write_action)
            wrapper.__mcp_write_action_resolver__ = write_action_resolver
            wrapper.__mcp_visibility__ = visibility
            wrapper.__mcp_tags__ = tag_list
            wrapper.__mcp_ui__ = ui_meta or None

            # Ensure schema + invocation messages are visible in clients that only render
            # the tool description (e.g., Actions list). Keep it compact.
            if show_schema_in_description:
                try:
                    schema_inline = _schema_summary(schema)
                except Exception:
                    schema_inline = ""
                if schema_inline:
                    normalized_description = (normalized_description or "").strip()
                    first, *rest = normalized_description.splitlines() if normalized_description else [""]
                    first = (first or "").strip()
                    if first and "Schema:" not in first:
                        first = f"{first}  Schema: {schema_inline}"
                    elif not first:
                        first = f"Schema: {schema_inline}"
                    normalized_description = "\n".join([first] + rest).strip()

            try:
                inv_line = str(ui_meta.get("invoking") or "").strip()
                done_line = str(ui_meta.get("invoked") or "").strip()
                if inv_line and inv_line not in normalized_description:
                    normalized_description = (normalized_description + f"\n\n{inv_line}").strip()
                if done_line and done_line not in normalized_description:
                    normalized_description = (normalized_description + f"\n{done_line}").strip()
            except Exception:
                pass
            _apply_tool_metadata(
                wrapper.__mcp_tool__,
                schema,
                visibility,
                tags=tag_list,
                write_action=bool(write_action),
                write_allowed=_tool_write_allowed(write_action),
                ui=ui_meta or None,
            )

            _attach_tool_annotations(wrapper.__mcp_tool__, annotations)

            # Ensure every registered tool has a stable, detailed docstring surface.
            # Some clients show only func.__doc__.
            try:
                wrapper.__doc__ = _build_tool_docstring(
                    tool_name=tool_name,
                    description=normalized_description,
                    input_schema=schema,
                    write_action=bool(write_action),
                    visibility=str(visibility),
                    write_allowed=_tool_write_allowed(write_action),
                    tags=tag_list,
                    ui=ui_meta or None,
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
            meta = _extract_tool_meta(kwargs)
            clean_kwargs = _strip_tool_meta(kwargs)
            all_args = _bind_call_args(signature, args, clean_kwargs) if LOG_TOOL_CALLS else {}
            req = get_request_context()
            start = time.perf_counter()

            effective_write_action = bool(write_action)
            if callable(write_action_resolver):
                try:
                    basis = all_args if isinstance(all_args, Mapping) and all_args else clean_kwargs
                    effective_write_action = bool(write_action_resolver(basis))
                except Exception:
                    effective_write_action = bool(write_action)

            schema = getattr(wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
            schema_present = isinstance(schema, Mapping) and isinstance(schema_hash, str)
            _log_tool_start(
                tool_name=tool_name,
                call_id=call_id,
                write_action=effective_write_action,
                req=req,
                schema_hash=schema_hash if schema_present else None,
                schema_present=schema_present,
                all_args=all_args,
            )
            try:
                if _should_enforce_write_gate(req):
                    _enforce_write_allowed(tool_name, write_action=effective_write_action)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                structured_error = _emit_tool_error(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    start=start,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    req=req,
                    exc=exc,
                    phase="preflight",
                    all_args=all_args,
                )
                _log_tool_failure(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
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
                # Best-effort idempotency for inbound requests.
                result: Any
                if _should_enforce_write_gate(req):
                    ttl_s = _dedupe_ttl_seconds(
                        write_action=bool(effective_write_action), meta=meta
                    )
                    if ttl_s > 0:
                        key_args = (
                            _bind_call_args(signature, args, clean_kwargs)
                            if signature is not None
                            else dict(clean_kwargs)
                        )
                        dedupe_key = _dedupe_key(
                            tool_name=tool_name,
                            write_action=bool(effective_write_action),
                            req=req,
                            args=key_args,
                        )
                        result = _maybe_dedupe_call_sync(
                            dedupe_key, lambda: func(*args, **clean_kwargs), ttl_s=ttl_s
                        )
                    else:
                        result = func(*args, **clean_kwargs)
                else:
                    result = func(*args, **clean_kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                structured_error = _emit_tool_error(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    start=start,
                    schema_hash=schema_hash,
                    schema_present=True,
                    req=req,
                    exc=exc,
                    phase="execute",
                    all_args=all_args,
                )
                _log_tool_failure(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
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
            outcome = _tool_result_outcome(result)
            if outcome == "error" and isinstance(result, Mapping):
                _log_tool_returned_error(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    duration_ms=duration_ms,
                    result=result,
                    all_args=all_args,
                )
            elif outcome == "warning":
                _log_tool_warning(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    duration_ms=duration_ms,
                    result=result,
                    all_args=all_args,
                )
            else:
                _log_tool_success(
                    tool_name=tool_name,
                    call_id=call_id,
                    write_action=effective_write_action,
                    req=req,
                    schema_hash=schema_hash if schema_present else None,
                    schema_present=schema_present,
                    duration_ms=duration_ms,
                    result=result,
                    all_args=all_args,
                )
            client_payload: Any
            if isinstance(result, Mapping):
                client_payload = _strip_internal_log_fields(result)
                if callable(write_action_resolver):
                    try:
                        client_payload = dict(client_payload)
                        client_payload.setdefault(
                            "tool_metadata",
                            {
                                "base_write_action": bool(write_action),
                                "effective_write_action": bool(effective_write_action),
                            },
                        )
                    except Exception:
                        pass
            else:
                client_payload = result
            if REDACT_TOOL_OUTPUTS and _effective_response_mode(req) in {"chatgpt", "compact"}:
                try:
                    client_payload = redact_any(client_payload)
                except Exception:
                    # Best-effort: never break tool behavior.
                    pass
            return _chatgpt_friendly_result(client_payload, req=req)

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            description=normalized_description,
            tags=tag_list,
            annotations=annotations,
        )

        schema = _normalize_input_schema(wrapper.__mcp_tool__)
        if not isinstance(schema, Mapping):
            schema = _schema_from_signature(signature, tool_name=tool_name)
        if not isinstance(schema, Mapping):
            raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")
        wrapper.__mcp_input_schema__ = schema
        wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)
        wrapper.__mcp_tool_name__ = tool_name
        wrapper.__mcp_write_action__ = bool(write_action)
        wrapper.__mcp_write_action_resolver__ = write_action_resolver
        wrapper.__mcp_visibility__ = visibility
        wrapper.__mcp_tags__ = tag_list
        wrapper.__mcp_ui__ = ui_meta or None

        if show_schema_in_description:
            try:
                schema_inline = _schema_summary(schema)
            except Exception:
                schema_inline = ""
            if schema_inline:
                normalized_description = (normalized_description or "").strip()
                first, *rest = normalized_description.splitlines() if normalized_description else [""]
                first = (first or "").strip()
                if first and "Schema:" not in first:
                    first = f"{first}  Schema: {schema_inline}"
                elif not first:
                    first = f"Schema: {schema_inline}"
                normalized_description = "\n".join([first] + rest).strip()

        try:
            inv_line = str(ui_meta.get("invoking") or "").strip()
            done_line = str(ui_meta.get("invoked") or "").strip()
            if inv_line and inv_line not in normalized_description:
                normalized_description = (normalized_description + f"\n\n{inv_line}").strip()
            if done_line and done_line not in normalized_description:
                normalized_description = (normalized_description + f"\n{done_line}").strip()
        except Exception:
            pass
        _apply_tool_metadata(
            wrapper.__mcp_tool__,
            schema,
            visibility,
            tags=tag_list,
            write_action=bool(write_action),
            write_allowed=_tool_write_allowed(write_action),
            ui=ui_meta or None,
        )

        _attach_tool_annotations(wrapper.__mcp_tool__, annotations)

        # Ensure every registered tool has a stable, detailed docstring surface.
        # Some clients show only func.__doc__.
        try:
            wrapper.__doc__ = _build_tool_docstring(
                tool_name=tool_name,
                description=normalized_description,
                input_schema=schema,
                write_action=bool(write_action),
                visibility=str(visibility),
                write_allowed=_tool_write_allowed(write_action),
                tags=tag_list,
                ui=ui_meta or None,
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

            ui = None
            try:
                ui = getattr(func, "__mcp_ui__", None)
            except Exception:
                ui = None

            _apply_tool_metadata(
                tool_obj,
                schema,
                visibility,
                write_action=base_write,
                write_allowed=allowed,
                ui=ui if isinstance(ui, Mapping) else None,
            )

            # Keep the tool description aligned (for UIs that only render description).
            if isinstance(schema, Mapping):
                try:
                    desc = getattr(tool_obj, "description", None)
                    if isinstance(desc, str) and desc:
                        schema_inline = _schema_summary(schema)
                        if schema_inline and "Schema:" not in desc.splitlines()[0]:
                            first, *rest = desc.splitlines()
                            first = (first or "").strip() + f"  Schema: {schema_inline}"
                            setattr(tool_obj, "description", "\n".join([first] + rest).strip())
                except Exception:
                    pass
        except Exception:
            continue

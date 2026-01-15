"""github_mcp.mcp_server.decorators

Decorators and helpers for registering MCP tools.

Behavioral contract:
- The server does not hard-block write tools; clients decide whether to prompt.
- Tools publish input schemas for introspection, but the server does NOT
 enforce JSONSchema validation at runtime.
- Tags are accepted for backwards compatibility but are not emitted to clients.
- Dedupe helpers remain for compatibility and test coverage.

Dedupe contract:
- Async dedupe caches completed results for a short TTL within the SAME event loop.
- Async dedupe is scoped per event loop (does not share futures across loops).
- Sync dedupe memoizes results for TTL.
"""

from __future__ import annotations

import asyncio
import importlib
import functools
import hashlib
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
    LOG_TOOL_CALL_STARTS,
    LOG_TOOL_CALLS,
    LOG_TOOL_PAYLOADS,
    shorten_token,
    summarize_request_context,
)
from github_mcp.exceptions import UsageError
from github_mcp.mcp_server.context import (
    WRITE_ALLOWED,
    get_request_context,
    mcp,
    FASTMCP_AVAILABLE,
)
from github_mcp.mcp_server.errors import _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS, _registered_tool_name
from github_mcp.mcp_server.schemas import (
    _schema_from_signature,
    _normalize_input_schema,
    _normalize_tool_description,
    _build_tool_docstring,
)


# Intentionally short logger name; config's formatter further shortens/colorizes.
LOGGER = BASE_LOGGER.getChild("mcp")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


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

# Reduce log noise by omitting correlation IDs from INFO/WARN message strings.
# Structured JSON extras still include the full request context.
LOG_TOOL_LOG_IDS = _env_flag("GITHUB_MCP_LOG_IDS", default=False)

LOG_TOOL_VISUAL_MAX_LINES = _env_int("GITHUB_MCP_LOG_VISUAL_MAX_LINES", default=80)
LOG_TOOL_READ_MAX_LINES = _env_int("GITHUB_MCP_LOG_READ_MAX_LINES", default=40)
LOG_TOOL_VISUAL_MAX_CHARS = _env_int("GITHUB_MCP_LOG_VISUAL_MAX_CHARS", default=8000)


ANSI_RESET = "\x1b[0m"
ANSI_DIM = "\x1b[2m"
ANSI_RED = "\x1b[31m"
ANSI_GREEN = "\x1b[32m"
ANSI_YELLOW = "\x1b[33m"
ANSI_CYAN = "\x1b[36m"


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
            PythonTracebackLexer,
            PythonLexer,
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
        return highlight(text, lexer, Terminal256Formatter(style="default")).rstrip("\n")
    except Exception:
        return text


def _highlight_file_text(path: str, text: str) -> str:
    """Highlight file text by filename when possible."""

    if not (LOG_TOOL_COLOR and _pygments_available() and isinstance(text, str) and text):
        return text
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import get_lexer_for_filename, TextLexer

        try:
            lexer = get_lexer_for_filename(path or "", text)
        except Exception:
            lexer = TextLexer()
        return highlight(text, lexer, Terminal256Formatter(style="default")).rstrip("\n")
    except Exception:
        return text


def _ansi(text: str, code: str) -> str:
    if not LOG_TOOL_COLOR:
        return text
    return f"{code}{text}{ANSI_RESET}"


# Friendly tool naming for developer-facing logs.
_TOOL_FRIENDLY_NAMES: dict[str, str] = {
    "validate_environment": "Environment check",
    "get_server_config": "Server config",
    "ensure_workspace_clone": "Workspace sync",
    "workspace_create_branch": "Create branch",
    "workspace_delete_branch": "Delete branch",
    "commit_workspace": "Commit changes",
    "open_pr_for_existing_branch": "Open pull request",
    "apply_patch": "Apply patch",
    "get_workspace_file_contents": "Read file",
    "set_workspace_file_contents": "Write file",
    "delete_workspace_paths": "Delete paths",
    "list_workspace_files": "List files",
    "search_workspace": "Search workspace",
    "terminal_command": "Run command",
    "render_shell": "Run shell",
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
        bits.append(f"\"{title.strip()}\"")

    base = all_args.get("base")
    head = all_args.get("head") or all_args.get("branch")
    if isinstance(head, str) and head:
        if isinstance(base, str) and base:
            bits.append(f"{head} -> {base}")
        else:
            bits.append(head)

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
    if not diff_text:
        return ""
    header = "diff"
    body = diff_text
    try:
        from github_mcp.diff_utils import diff_stats

        stats = diff_stats(diff_text)
        header = f"diff (+{stats.added} -{stats.removed})"
    except Exception:
        pass

    if LOG_TOOL_COLOR:
        # Prefer Pygments (more Python-like) when available.
        body = _highlight_code(diff_text, kind="diff")
    else:
        body = _non_ansi_diff_markers(diff_text)

    # Add line numbers for scannability.
    numbered: list[str] = []
    for idx, line in enumerate(body.splitlines(), start=1):
        ln = _ansi(f"{idx:>4}│", ANSI_DIM)
        numbered.append(f"{ln} {line}")
    clipped = _clip_text(
        "\n".join(numbered),
        max_lines=LOG_TOOL_VISUAL_MAX_LINES,
        max_chars=LOG_TOOL_VISUAL_MAX_CHARS,
    )
    return _ansi(header, ANSI_CYAN) + "\n" + clipped


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


def _preview_file_snippet(path: str, text: str) -> str:
    highlighted = _highlight_file_text(path, text or "")
    lines = highlighted.splitlines()
    max_lines = max(1, LOG_TOOL_READ_MAX_LINES)
    preview = lines[:max_lines]
    rendered: list[str] = []
    for idx, line in enumerate(preview, start=1):
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
    header = _ansi(kind or "visual", ANSI_CYAN) + " " + _ansi(_friendly_tool_name(tool_name), ANSI_CYAN)
    if kv:
        header = header + " " + kv
    LOGGER.info(
        f"{header}\n{visual}",
        extra={
            "event": "tool_visual",
            "tool": tool_name,
            "kind": kind,
            "call_id": shorten_token(call_id),
        },
    )


def _truncate_text(value: Any, *, limit: int = 180) -> str:
    try:
        s = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
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

    To allow logging of sensitive fields (not recommended), set:
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
    # for whether a confirmation prompt is required. The server itself does not
    # block write tools.
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
    except asyncio.CancelledError:
        # Preserve cancellation semantics. Avoid turning cancellation into a
        # cached exception and ensure future waiters are cancelled as well.
        if not fut.done():
            fut.cancel()
        async with lock:
            cur = _DEDUPE_ASYNC_CACHE.get(cache_key)
            if cur and cur[1] is fut:
                _DEDUPE_ASYNC_CACHE.pop(cache_key, None)
        raise
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


def _extract_tool_meta(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract the optional _meta payload without mutating kwargs.

    _meta is reserved for client-side execution hints. The server ignores
    unknown keys, but may use a small subset for safe runtime behaviors like
    idempotency.
    """

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
    if write_action:
        raw = os.environ.get("GITHUB_MCP_TOOL_DEDUPE_TTL_WRITE_S", "60")
    else:
        raw = os.environ.get("GITHUB_MCP_TOOL_DEDUPE_TTL_READ_S", "15")
    try:
        return max(0.0, float(raw))
    except Exception:
        return 0.0


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
    # IMPORTANT: request_id is commonly regenerated on retries. Including it
    # when a more stable scope exists prevents dedupe from working and can
    # cause the same tool call to be executed multiple times.
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
        "call_id": shorten_token(call_id),
        "write_action": bool(write_action),
        "schema_hash": shorten_token(schema_hash) if schema_present else None,
        "schema_present": bool(schema_present),
        "request": summarize_request_context(req),
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
    # Default: avoid logging both start + completion for every tool call.
    # Completion logs already include correlation ids + duration.
    if not LOG_TOOL_CALLS or not LOG_TOOL_CALL_STARTS:
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
    # Developer-facing, human-readable line (provider log UIs show message strings most prominently).
    friendly = _friendly_tool_name(tool_name)
    bits = _friendly_arg_bits(all_args)
    suffix = (" - " + " - ".join(bits)) if bits else ""
    prefix = _ansi("▶", ANSI_GREEN) + " " + _ansi(friendly, ANSI_CYAN)
    msg = f"{prefix}{suffix}"
    if LOG_TOOL_LOG_IDS:
        msg = msg + " " + _ansi(f"[{shorten_token(call_id)}]", ANSI_DIM)
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
        friendly = _friendly_tool_name(tool_name)
        bits = _friendly_arg_bits(all_args or {})
        suffix = (" - " + " - ".join(bits)) if bits else ""
        prefix = _ansi("✓", ANSI_GREEN) + " " + _ansi(friendly, ANSI_CYAN)
        ms = _ansi(f"({duration_ms:.0f}ms)", ANSI_DIM)
        msg = f"{prefix} {ms}{suffix}"
        if LOG_TOOL_LOG_IDS:
            msg = msg + " " + _ansi(f"[{shorten_token(call_id)}]", ANSI_DIM)
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
                    diff_candidate = result.get("diff") or result.get("patch")
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
                        kind = "changes"
                        visual = _preview_changed_files(status_lines)

                # 3) File reads (show which file + a snippet)
                if (
                    not visual
                    and LOG_TOOL_READ_SNIPPETS
                    and isinstance(result, Mapping)
                    and isinstance(result.get("path"), str)
                    and isinstance(result.get("text"), str)
                ):
                    # Only preview on read tools to avoid echoing writes unless explicitly enabled.
                    if not bool(write_action):
                        kind = "read"
                        visual = _preview_file_snippet(
                            str(result.get("path") or ""), str(result.get("text") or "")
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
        except Exception:
            # Visual logging is best-effort.
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
        LOGGER.info(f"{prefix} {line}", extra={"event": "tool_call_completed", **payload})


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
    prefix = _ansi("✗", ANSI_RED) + " " + _ansi(_friendly_tool_name(tool_name), ANSI_CYAN)
    LOGGER.warning(
        f"{prefix} {line}",
        extra={"event": "tool_call_failed", **payload},
        exc_info=exc,
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
    """Register a tool with FastMCP across signature variants.

    FastMCP has had multiple API shapes over time ("factory" vs "direct" tool
    registration). This helper attempts registration in a compatibility order
    while avoiding the common failure:

      TypeError: FastMCP.tool() got multiple values for argument 'name'

    Notes for developers:
      - Tags are intentionally suppressed. Some downstream clients interpret tags
        as execution/policy hints.
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
        _REGISTERED_MCP_TOOLS[:] = [
            (t, f) for (t, f) in _REGISTERED_MCP_TOOLS if _registered_tool_name(t, f) != name
        ]
        _REGISTERED_MCP_TOOLS.append((tool_obj, fn))
        return tool_obj

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
    tags: Optional[Iterable[str]] = None,  # noqa: ARG001
    description: str | None = None,
    visibility: str = "public",  # accepted, ignored
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare an MCP tool with developer-oriented metadata.

    This decorator is the canonical way to expose a Python callable via the
    GitHub MCP server. It wraps the function to provide:

    - Structured error payloads (top-level 'error' plus 'error_detail')
    - Optional write-action gating semantics (write_action=True)
    - Best-effort request-level idempotency/deduplication (see _meta)
    - Stable input schema generation for clients (signature-based fallback)

    Parameters:
      name: Optional override for the tool name (defaults to function __name__).
      write_action: Whether the tool performs mutations (git push, PR creation, etc.).
      description: Optional human/developer-facing description (defaults to func.__doc__).
      visibility: Currently accepted for compatibility; reported via introspection.
      tags: Accepted for compatibility but intentionally ignored.

    Reserved argument (_meta):
      Tools may accept an optional '_meta' kwarg. This is stripped before calling
      the underlying function and is used only for safe runtime behaviors.
      Supported keys: dedupe (bool), dedupe_ttl_s/dedupe_ttl_seconds (number),
      idempotency_key/dedupe_key (string).

    Error contract:
      On failure, tools return a JSON object with 'error' and a structured
      'error_detail'. HTTP clients additionally map common categories to status codes.

    """

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
                meta = _extract_tool_meta(kwargs)
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
                except asyncio.CancelledError:
                    raise
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
                    # Best-effort idempotency for inbound requests. This prevents
                    # accidental duplicate execution when an agent repeats the same
                    # tool call (common when model-side planning loops happen).
                    result: Any
                    if _should_enforce_write_gate(req):
                        ttl_s = _dedupe_ttl_seconds(write_action=bool(write_action), meta=meta)
                        if ttl_s > 0:
                            # Include all bound args for the key (positional + kwargs).
                            key_args = (
                                _bind_call_args(signature, args, clean_kwargs)
                                if signature is not None
                                else dict(clean_kwargs)
                            )
                            dedupe_key = _dedupe_key(
                                tool_name=tool_name,
                                write_action=bool(write_action),
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
                    all_args=all_args,
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
            wrapper.__mcp_tool_name__ = tool_name
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
            meta = _extract_tool_meta(kwargs)
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
            except asyncio.CancelledError:
                raise
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
                # Best-effort idempotency for inbound requests.
                result: Any
                if _should_enforce_write_gate(req):
                    ttl_s = _dedupe_ttl_seconds(write_action=bool(write_action), meta=meta)
                    if ttl_s > 0:
                        key_args = (
                            _bind_call_args(signature, args, clean_kwargs)
                            if signature is not None
                            else dict(clean_kwargs)
                        )
                        dedupe_key = _dedupe_key(
                            tool_name=tool_name,
                            write_action=bool(write_action),
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
                all_args=all_args,
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
        wrapper.__mcp_tool_name__ = tool_name
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

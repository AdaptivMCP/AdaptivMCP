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


# --- Tool visibility + routing metadata (ChatGPT-facing) ---
# Make tool routing and side-effects explicit for both humans and machines.
# Primary goal: prevent tool-surface ambiguity (server/admin vs workspace clone vs GitHub API).


def _infer_tool_surface(tool_name: str) -> str:
    tn = (tool_name or '').lower()

    # Workspace (local clone)
    if (
        'workspace' in tn
        or tn.startswith('workspace_')
        or tn.startswith('ensure_workspace')
        or tn.startswith('get_workspace')
        or tn.startswith('set_workspace')
        or tn.startswith('list_workspace')
        or tn.startswith('search_workspace')
        or tn in {'render_shell', 'terminal_command', 'run_command', 'run_tests', 'run_lint_suite', 'run_quality_suite'}
    ):
        return 'workspace'

    # Server/admin diagnostics
    if (
        tn.startswith('ping')
        or tn.startswith('validate_')
        or tn.startswith('get_recent_')
        or tn in {'list_tools', 'list_all_actions', 'describe_tool', 'get_repo_defaults', 'authorize_write_actions', 'get_server_config', 'list_render_logs', 'get_render_metrics'}
    ):
        return 'server_admin'

    # Default to GitHub API surface
    return 'github_api' if tn else 'unknown'


def _routing_hint(surface: str) -> dict[str, str]:
    if surface == 'workspace':
        return {
            'summary': 'Use for operations on the local workspace clone (Render filesystem).',
            'example': 'Edit/search/run commands in the staged repo clone.',
        }
    if surface == 'github_api':
        return {
            'summary': 'Use for operations against GitHub (remote API / live repo state).',
            'example': 'Fetch file contents from GitHub, open PRs, manage issues.',
        }
    if surface == 'server_admin':
        return {
            'summary': 'Use for server/admin/diagnostics endpoints (not repo content).',
            'example': 'Ping, list tools, validate environment, fetch recent logs/errors.',
        }
    return {
        'summary': 'Routing surface unknown; use describe_tool/list_tools to confirm.',
        'example': 'Call describe_tool to inspect expected arguments and purpose.',
    }


def _build_tool_descriptor(
    *,
    tool_name: str,
    title: str,
    description: str | None,
    visibility: str,
    tags: Iterable[str],
    read_only_hint: bool,
    side_effects: str,
    remote_write: bool,
    ui_write_action: bool,
    write_allowed: bool,
    schema_fingerprint: str,
    schema_visibility: str,
) -> dict[str, Any]:
    surface = _infer_tool_surface(tool_name)
    return {
        'name': tool_name,
        'title': title,
        'description': (description or '').strip(),
        'visibility': visibility,
        'tags': sorted(set([t for t in tags if t])),
        'surface': surface,
        'routing_hint': _routing_hint(surface),
        'read_only_hint': bool(read_only_hint),
        'side_effects': side_effects,
        'remote_write': bool(remote_write),
        'ui_write_action': bool(ui_write_action),
        'write_allowed': bool(write_allowed),
        'schema': {
            'fingerprint': schema_fingerprint,
            'visibility': schema_visibility,
        },
    }


def _build_tool_descriptor_text(d: Mapping[str, Any]) -> str:
    rh = d.get('routing_hint') or {}
    schema = d.get('schema') or {}
    tags = d.get('tags') or []

    lines = [
        f"Tool: {d.get('title','')} ({d.get('name','')})",
        f"Surface: {d.get('surface','')}",
        f"Visibility: {d.get('visibility','')}",
        f"Side effects: {d.get('side_effects','')}",
        f"Read-only hint: {d.get('read_only_hint', False)}",
        f"Remote write: {d.get('remote_write', False)}",
        f"UI write action: {d.get('ui_write_action', False)}",
        f"Write allowed: {d.get('write_allowed', False)}",
        f"Schema fingerprint: {schema.get('fingerprint','')}",
        f"Schema visibility: {schema.get('visibility','')}",
        ("Tags: " + ", ".join(tags)) if tags else 'Tags: (none)',
        f"Routing: {rh.get('summary','')}",
        f"Routing example: {rh.get('example','')}",
    ]

    desc = (d.get('description') or '').strip()
    if desc:
        lines.append('Description: ' + desc)

    return "\n".join(lines)


def _lookup_tool_descriptor(tool_name: str) -> dict[str, Any] | None:
    tn = str(tool_name or '')
    for tool_obj, fn in reversed(list(_REGISTERED_MCP_TOOLS)):
        try:
            if getattr(tool_obj, 'name', None) == tn or getattr(fn, '__name__', None) == tn:
                meta = getattr(tool_obj, 'meta', {}) or {}
                desc = meta.get('tool_descriptor')
                if isinstance(desc, dict):
                    return {
                        'tool_descriptor': desc,
                        'tool_descriptor_text': meta.get('tool_descriptor_text'),
                        'tool_surface': desc.get('surface'),
                        'routing_hint': desc.get('routing_hint'),
                    }
        except Exception:
            continue
    return None


def _auto_approved_for_tool(
    tool_name: str,
    *,
    side_effect: SideEffectClass,
    write_allowed: bool,
) -> bool:
    """Compute connector-side auto-approval for a tool.

    Policy:
      - Reads are always auto-approved.
      - Soft writes are auto-approved iff WRITE_ALLOWED is true.
      - Hard writes are never auto-approved.
      - Render CLI tools never require approval.
      - Web fetch requires approval when WRITE_ALLOWED is false.
    """
    # Render CLI tools (explicitly never require approval)
    if tool_name.startswith('render_') or tool_name in {'render_shell', 'terminal_command', 'run_command'}:
        return True

    # Web tool policy
    if tool_name == 'fetch_url':
        return bool(write_allowed)

    if side_effect is SideEffectClass.READ_ONLY:
        return True

    if side_effect is SideEffectClass.LOCAL_MUTATION:
        return bool(write_allowed)

    # Remote mutation (hard write)
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
    """Emit a single machine-parseable JSON record for tool lifecycle events."""
    try:
        base = dict(payload)
        if 'tool_name' in base and 'tool_descriptor' not in base:
            injected = _lookup_tool_descriptor(str(base.get('tool_name') or ''))
            if injected:
                for k, v in injected.items():
                    base.setdefault(k, v)
        safe = _sanitize_metadata_value(base)
        raw = json.dumps(
            safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        TOOLS_LOGGER.detailed(
            f"[tool json] {raw}",
            extra={
                "event": "tool_json",
                "status": payload.get("status"),
                "tool_name": payload.get("tool_name"),
                "call_id": payload.get("call_id"),
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


def _dedupe_key(
    tool_name: str, *, ui_write_action: bool, args_preview: str
) -> Optional[str]:
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
        "chatgpt.com/visibility": visibility,
        "chatgpt.com/read_only_hint": read_only_hint,
        "chatgpt.com/toolInvocation/invoking": OPENAI_INVOKING_MESSAGE,
        "chatgpt.com/toolInvocation/invoked": OPENAI_INVOKED_MESSAGE,
    }

    if title:
        meta["chatgpt.com/title"] = title

    annotations = {"title": title or _title_from_tool_name(name)}
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
    tool_obj.meta["chatgpt.com/auto_approved"] = _auto_approved_for_tool(
        name,
        side_effect=side_effect,
        write_allowed=wa,
    )
    tool_obj.meta["chatgpt.com/side_effects"] = side_effect.value

    # Schema fingerprint + routing/visibility descriptor (ChatGPT-facing).
    schema_norm = _normalize_input_schema(tool_obj)
    try:
        schema_json = json.dumps(schema_norm, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    except Exception:
        schema_json = ''
    schema_fingerprint = (
        hashlib.sha1(schema_json.encode('utf-8', errors='replace')).hexdigest()
        if schema_json
        else ''
    )
    tool_obj.meta['schema_fingerprint'] = schema_fingerprint
    tool_obj.meta['schema_visibility'] = visibility
    for domain_prefix in ('chatgpt.com',):
        tool_obj.meta[f'{domain_prefix}/schema_fingerprint'] = schema_fingerprint
        tool_obj.meta[f'{domain_prefix}/schema_visibility'] = visibility

    descriptor = _build_tool_descriptor(
        tool_name=name,
        title=(title or _title_from_tool_name(name)),
        description=description,
        visibility=visibility,
        tags=tags,
        read_only_hint=read_only_hint,
        side_effects=side_effect.value,
        remote_write=bool(remote_write),
        ui_write_action=bool(ui_write_action),
        write_allowed=bool(wa),
        schema_fingerprint=schema_fingerprint,
        schema_visibility=visibility,
    )
    descriptor = _sanitize_metadata_value(descriptor)
    tool_obj.meta['tool_descriptor'] = descriptor
    tool_obj.meta['tool_descriptor_text'] = _build_tool_descriptor_text(descriptor)
    tool_obj.meta['tool_surface'] = descriptor.get('surface')
    tool_obj.meta['routing_hint'] = (descriptor.get('routing_hint') or {})
    for domain_prefix in ('chatgpt.com',):
        tool_obj.meta[f'{domain_prefix}/tool_descriptor'] = descriptor
        tool_obj.meta[f'{domain_prefix}/tool_descriptor_text'] = tool_obj.meta['tool_descriptor_text']
        tool_obj.meta[f'{domain_prefix}/tool_surface'] = tool_obj.meta['tool_surface']
        tool_obj.meta[f'{domain_prefix}/routing_hint'] = tool_obj.meta['routing_hint']

    try:
        fn.__tool_descriptor__ = descriptor
        fn.__tool_descriptor_text__ = tool_obj.meta['tool_descriptor_text']
    except Exception:
        pass

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
        side_effect = (
            SideEffectClass.REMOTE_MUTATION
            if remote_write
            else resolve_side_effect_class(tool_name)
        )

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

                start = time.perf_counter()
                request_ctx = get_request_context()
                dedupe_key = _dedupe_key(
                    tool_name,
                    ui_write_action=ui_write_action,
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
                            tool_name, write_action=ui_write_action, phase="start"
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(
                        tool_name, write_action=ui_write_action, phase="start"
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
                            "error_type": exc.__class__.__name__,
                            "error_message": str(
                                error_info.get("message") or exc.__class__.__name__
                            ),
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
                        "result_type": result_type,
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=ui_write_action,
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
                        "result_type": result_type,
                    }
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
            dedupe_key = _dedupe_key(
                tool_name,
                ui_write_action=ui_write_action,
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
                        tool_name, write_action=ui_write_action, phase="start"
                    ),
                }
            )

            TOOLS_LOGGER.chat(
                _tool_user_message(
                    tool_name, write_action=ui_write_action, phase="start"
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
                        "error_type": exc.__class__.__name__,
                        "error_message": str(
                            error_info.get("message") or exc.__class__.__name__
                        ),
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
                    "result_type": result_type,
                    "user_message": _tool_user_message(
                        tool_name,
                        write_action=ui_write_action,
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
                    "result_type": result_type,
                }
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
    effective_write_allowed = (
        _current_write_allowed() if _write_allowed is None else bool(_write_allowed)
    )

    for tool_obj, fn in list(_REGISTERED_MCP_TOOLS):
        try:
            tool_name = str(getattr(tool_obj, "name", None) or getattr(fn, "__name__", "tool"))
            side_effect = getattr(fn, "__side_effect_class__", None)
            if not isinstance(side_effect, SideEffectClass):
                side_effect = resolve_side_effect_class(tool_name)
            tool_obj.meta["chatgpt.com/auto_approved"] = _auto_approved_for_tool(
                tool_name,
                side_effect=side_effect,
                write_allowed=effective_write_allowed,
            )
        except Exception:
            continue

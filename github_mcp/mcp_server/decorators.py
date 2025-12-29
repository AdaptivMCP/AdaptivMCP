"""
Decorators and helpers for registering MCP tools.

Design goals for this version:
- The only blocking/guardrail is WRITE_ALLOWED (true/false) for write tools.
- Every tool call is validated against its published input schema (no guessing).
- No tag-based behavior, no side-effect classification, no dedupe suppression,
  no UI prompts. Logging remains for observability.
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
from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
from github_mcp.mcp_server.schemas import (
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _jsonable,
)
from github_mcp.metrics import _record_tool_call


def _schema_hash(schema: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        raw = str(schema)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _require_jsonschema() -> Any:
    """
    Enforce strict schema validation.
    If jsonschema isn't installed, we fail fast rather than silently skipping validation.
    """
    try:
        import jsonschema  # type: ignore

        return jsonschema
    except Exception as exc:
        raise AdaptivToolError(
            code="schema_validation_unavailable",
            message="jsonschema is required for strict tool argument validation but is not installed.",
            category="validation",
            origin="schema",
            retryable=False,
            details={"missing_dependency": "jsonschema"},
            hint="Add jsonschema to your server dependencies (pip install jsonschema) and redeploy.",
        ) from exc


def _validate_tool_args_schema(
    tool_name: str,
    schema: Mapping[str, Any],
    args: Mapping[str, Any],
) -> None:
    jsonschema = _require_jsonschema()

    # Strip method receiver if present.
    payload = dict(args)
    payload.pop("self", None)

    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(payload), key=str)
    except Exception as exc:
        raise AdaptivToolError(
            code="tool_schema_validation_failed",
            message=f"Tool schema validation failed for {tool_name!r}: {exc}",
            category="validation",
            origin="schema",
            retryable=False,
            details={"tool": tool_name},
            hint="Inspect the tool schema via tool_schema/tool_spec or schema_catalog, then resend args that conform exactly.",
        ) from exc

    if not errors:
        return

    error_list: list[dict[str, Any]] = []
    for err in errors[:50]:
        try:
            error_list.append(
                {
                    "message": getattr(err, "message", str(err)),
                    "path": list(getattr(err, "absolute_path", []) or []),
                    "validator": getattr(err, "validator", None),
                    "validator_value": getattr(err, "validator_value", None),
                }
            )
        except Exception:
            error_list.append({"message": str(err)})

    raise AdaptivToolError(
        code="tool_args_invalid",
        message=f"Tool arguments did not match schema for {tool_name!r}.",
        category="validation",
        origin="schema",
        retryable=False,
        details={"tool": tool_name, "errors": error_list, "schema": dict(schema)},
        hint="Fetch the tool schema and resend args that conform exactly. Do not guess fields.",
    )


def _current_write_allowed() -> bool:
    try:
        import github_mcp.server as server_mod

        return bool(getattr(server_mod, "WRITE_ALLOWED", False))
    except Exception:
        return False


def _enforce_write_allowed(tool_name: str, write_action: bool) -> None:
    if not write_action:
        return
    if _current_write_allowed():
        return
    raise AdaptivToolError(
        code="write_not_allowed",
        message=f"Write tool {tool_name!r} blocked because WRITE_ALLOWED is false.",
        category="policy",
        origin="write_gate",
        retryable=False,
        details={"tool": tool_name, "write_allowed": False},
        hint="Set WRITE_ALLOWED=true (or enable writes via your server config) and retry.",
    )


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
    arg_keys = sorted(all_args.keys())
    arg_preview = _format_tool_args_preview(all_args)
    return {"arg_keys": arg_keys, "arg_count": len(all_args), "arg_preview": arg_preview}


def _log_tool_json_event(payload: Mapping[str, Any]) -> None:
    try:
        safe = _jsonable(dict(payload))
        tool_name = str(payload.get("tool_name") or "")
        status = str(payload.get("status") or "")
        call_id = str(payload.get("call_id") or "")
        evt = str(payload.get("event") or "tool_json")
        duration_ms = payload.get("duration_ms")
        dur = f" | duration_ms={duration_ms}" if isinstance(duration_ms, (int, float)) else ""
        msg = f"[tool event] {evt} | status={status} | tool={tool_name} | call_id={call_id}{dur}"

        TOOLS_LOGGER.detailed(
            msg,
            extra={
                "event": "tool_json",
                "status": payload.get("status"),
                "tool_name": payload.get("tool_name"),
                "call_id": payload.get("call_id"),
                "tool_event": safe,
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
    dur = f" ({duration_ms}ms)" if duration_ms is not None else ""
    if phase == "start":
        return f"→ {tool_name} [{scope}]"
    if phase == "ok":
        return f"← ok{dur}"
    if phase == "error":
        suffix = f" {error}" if error else ""
        return f"← error{dur}{suffix}"
    return f"{tool_name} [{scope}]"


def _stable_request_id() -> Optional[str]:
    msg_id = REQUEST_MESSAGE_ID.get()
    if msg_id:
        return msg_id
    sess_id = REQUEST_SESSION_ID.get()
    if sess_id:
        return sess_id
    return None


def _register_with_fastmcp(
    fn: Callable[..., Any],
    *,
    name: str,
    description: Optional[str],
    visibility: str = "public",
) -> Any:
    meta: dict[str, Any] = {}
    annotations: dict[str, Any] = {}

    tool_obj = mcp.tool(
        fn,
        name=name,
        description=description,
        tags=set(),  # explicitly ignore tags to prevent tag-based behavior upstream
        meta=meta,
        annotations=_jsonable(annotations),
    )

    # Keep registry stable.
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
    tags: Optional[Iterable[str]] = None,  # ignored on purpose
    description: str | None = None,
    visibility: str = "public",
    **_ignored: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator used across the repo to register an MCP tool.

    Enforcement invariants:
    - If write_action=True and WRITE_ALLOWED is false -> block with AdaptivToolError.
    - Validate every call against the tool's published input schema (strict).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        try:
            signature: Optional[inspect.Signature] = inspect.signature(func)
        except Exception:
            signature = None

        tool_name = name or getattr(func, "__name__", "tool")
        tool_visibility = _ignored.get("visibility", visibility)

        llm_level = "advanced" if write_action else "basic"
        normalized_description = description or _normalize_tool_description(
            func, signature, llm_level=llm_level
        )

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                all_args = _bind_call_args(signature, args, kwargs)

                # Strict schema: must exist and must validate.
                schema = getattr(wrapper, "__mcp_input_schema__", None)
                schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
                if not isinstance(schema, Mapping) or not schema_hash:
                    raise AdaptivToolError(
                        code="schema_missing",
                        message=f"Tool schema missing for {tool_name!r}. Refusing to run to avoid schema guessing.",
                        category="validation",
                        origin="schema",
                        retryable=False,
                        details={"tool": tool_name},
                        hint="Ensure tools are registered with input schemas and schema caching is enabled at startup.",
                    )

                _validate_tool_args_schema(tool_name, schema, all_args)
                _enforce_write_allowed(tool_name, write_action=write_action)

                ctx = _extract_context(all_args)
                start = time.perf_counter()
                request_ctx = get_request_context()

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "user_message": _tool_user_message(
                            tool_name, write_action=write_action, phase="start"
                        ),
                    }
                )

                TOOLS_LOGGER.chat(
                    _tool_user_message(tool_name, write_action=write_action, phase="start"),
                    extra={
                        "event": "tool_chat",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                    },
                )

                TOOLS_LOGGER.detailed(
                    f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                    extra={
                        "event": "tool_call_start",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                    },
                )

                _log_tool_json_event(
                    {
                        "event": "tool_call.start",
                        "status": "start",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "arg_keys": ctx["arg_keys"],
                        "arg_count": ctx["arg_count"],
                    }
                )

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name,
                        write_kind="write" if write_action else "read",
                        duration_ms=duration_ms,
                        errored=True,
                    )

                    structured_error = _structured_tool_error(exc, context=tool_name, path=None)
                    err_obj = structured_error.get("error", {}) if isinstance(structured_error, dict) else {}
                    err_msg = str(err_obj.get("message") or exc)

                    _record_recent_tool_event(
                        {
                            "ts": time.time(),
                            "event": "tool_recent_error",
                            "tool_name": tool_name,
                            "call_id": call_id,
                            "duration_ms": duration_ms,
                            "request": request_ctx,
                            "schema_hash": schema_hash,
                            "schema_present": True,
                            "write_action": bool(write_action),
                            "write_allowed": _current_write_allowed(),
                            "error_type": exc.__class__.__name__,
                            "error_message": err_msg,
                            "user_message": _tool_user_message(
                                tool_name,
                                write_action=write_action,
                                phase="error",
                                duration_ms=duration_ms,
                                error=f"{exc.__class__.__name__}: {exc}",
                            ),
                        }
                    )

                    TOOLS_LOGGER.error(
                        _tool_user_message(
                            tool_name,
                            write_action=write_action,
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
                            "schema_hash": schema_hash,
                            "schema_present": True,
                            "write_action": bool(write_action),
                            "write_allowed": _current_write_allowed(),
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
                            "schema_hash": schema_hash,
                            "schema_present": True,
                            "write_action": bool(write_action),
                            "write_allowed": _current_write_allowed(),
                            "error_type": exc.__class__.__name__,
                            "error_message": err_msg,
                        }
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name,
                    write_kind="write" if write_action else "read",
                    duration_ms=duration_ms,
                    errored=False,
                )

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "result_type": type(result).__name__,
                        "user_message": _tool_user_message(
                            tool_name, write_action=write_action, phase="ok", duration_ms=duration_ms
                        ),
                    }
                )

                TOOLS_LOGGER.detailed(
                    f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={type(result).__name__}",
                    extra={
                        "event": "tool_call_ok",
                        "status": "ok",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "result_type": type(result).__name__,
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
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "result_type": type(result).__name__,
                    }
                )

                return result

            # Register and cache schema/hash.
            wrapper.__mcp_tool__ = _register_with_fastmcp(
                wrapper,
                name=tool_name,
                description=normalized_description,
                visibility=tool_visibility,
            )

            schema = _normalize_input_schema(wrapper.__mcp_tool__)
            if not isinstance(schema, Mapping):
                raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")

            wrapper.__mcp_input_schema__ = schema
            wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)

            wrapper.__mcp_visibility__ = tool_visibility
            wrapper.__mcp_write_action__ = bool(write_action)
            return wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            all_args = _bind_call_args(signature, args, kwargs)

            schema = getattr(wrapper, "__mcp_input_schema__", None)
            schema_hash = getattr(wrapper, "__mcp_input_schema_hash__", None)
            if not isinstance(schema, Mapping) or not schema_hash:
                raise AdaptivToolError(
                    code="schema_missing",
                    message=f"Tool schema missing for {tool_name!r}. Refusing to run to avoid schema guessing.",
                    category="validation",
                    origin="schema",
                    retryable=False,
                    details={"tool": tool_name},
                    hint="Ensure tools are registered with input schemas and schema caching is enabled at startup.",
                )

            _validate_tool_args_schema(tool_name, schema, all_args)
            _enforce_write_allowed(tool_name, write_action=write_action)

            ctx = _extract_context(all_args)
            start = time.perf_counter()
            request_ctx = get_request_context()

            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_recent_start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": _current_write_allowed(),
                    "user_message": _tool_user_message(tool_name, write_action=write_action, phase="start"),
                }
            )

            TOOLS_LOGGER.chat(
                _tool_user_message(tool_name, write_action=write_action, phase="start"),
                extra={
                    "event": "tool_chat",
                    "status": "start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                },
            )

            TOOLS_LOGGER.detailed(
                f"[tool start] tool={tool_name} | call_id={call_id} | args={ctx['arg_preview']}",
                extra={
                    "event": "tool_call_start",
                    "status": "start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "arg_keys": ctx["arg_keys"],
                    "arg_count": ctx["arg_count"],
                    "request": request_ctx,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": _current_write_allowed(),
                },
            )

            _log_tool_json_event(
                {
                    "event": "tool_call.start",
                    "status": "start",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "request": request_ctx,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
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
                    write_kind="write" if write_action else "read",
                    duration_ms=duration_ms,
                    errored=True,
                )

                structured_error = _structured_tool_error(exc, context=tool_name, path=None)
                err_obj = structured_error.get("error", {}) if isinstance(structured_error, dict) else {}
                err_msg = str(err_obj.get("message") or exc)

                _record_recent_tool_event(
                    {
                        "ts": time.time(),
                        "event": "tool_recent_error",
                        "tool_name": tool_name,
                        "call_id": call_id,
                        "duration_ms": duration_ms,
                        "request": request_ctx,
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "error_type": exc.__class__.__name__,
                        "error_message": err_msg,
                        "user_message": _tool_user_message(
                            tool_name,
                            write_action=write_action,
                            phase="error",
                            duration_ms=duration_ms,
                            error=f"{exc.__class__.__name__}: {exc}",
                        ),
                    }
                )

                TOOLS_LOGGER.error(
                    _tool_user_message(
                        tool_name,
                        write_action=write_action,
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
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
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
                        "schema_hash": schema_hash,
                        "schema_present": True,
                        "write_action": bool(write_action),
                        "write_allowed": _current_write_allowed(),
                        "error_type": exc.__class__.__name__,
                        "error_message": err_msg,
                    }
                )
                raise

            duration_ms = int((time.perf_counter() - start) * 1000)
            _record_tool_call(
                tool_name,
                write_kind="write" if write_action else "read",
                duration_ms=duration_ms,
                errored=False,
            )

            _record_recent_tool_event(
                {
                    "ts": time.time(),
                    "event": "tool_recent_ok",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "request": request_ctx,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": _current_write_allowed(),
                    "result_type": type(result).__name__,
                    "user_message": _tool_user_message(
                        tool_name, write_action=write_action, phase="ok", duration_ms=duration_ms
                    ),
                }
            )

            TOOLS_LOGGER.detailed(
                f"[tool ok] tool={tool_name} | call_id={call_id} | duration_ms={duration_ms} | result_type={type(result).__name__}",
                extra={
                    "event": "tool_call_ok",
                    "status": "ok",
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "request": request_ctx,
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": _current_write_allowed(),
                    "result_type": type(result).__name__,
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
                    "schema_hash": schema_hash,
                    "schema_present": True,
                    "write_action": bool(write_action),
                    "write_allowed": _current_write_allowed(),
                    "result_type": type(result).__name__,
                }
            )

            return result

        wrapper.__mcp_tool__ = _register_with_fastmcp(
            wrapper,
            name=tool_name,
            description=normalized_description,
            visibility=tool_visibility,
        )

        schema = _normalize_input_schema(wrapper.__mcp_tool__)
        if not isinstance(schema, Mapping):
            raise RuntimeError(f"Failed to derive input schema for tool {tool_name!r}.")

        wrapper.__mcp_input_schema__ = schema
        wrapper.__mcp_input_schema_hash__ = _schema_hash(schema)

        wrapper.__mcp_visibility__ = tool_visibility
        wrapper.__mcp_write_action__ = bool(write_action)
        return wrapper

    return decorator


def register_extra_tools_if_available() -> None:
    try:
        from extra_tools import register_extra_tools  # type: ignore

        register_extra_tools(mcp_tool)
    except Exception:
        return None


def refresh_registered_tool_metadata(_write_allowed: object = None) -> None:
    # No-op: no dynamic tag/guardrail metadata to refresh.
    return None
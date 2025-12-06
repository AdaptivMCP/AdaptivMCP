"""Shared server setup and decorator utilities for the GitHub MCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from typing import Any, Dict, Mapping, Optional

import jsonschema
from anyio import ClosedResourceError
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from github_mcp import http_clients as _http_clients
from github_mcp.config import BASE_LOGGER, TOOLS_LOGGER
from github_mcp.exceptions import WriteNotAuthorizedError
from github_mcp.http_clients import (
    _concurrency_semaphore,
    _external_client_instance,
    _github_client_instance,
)
from github_mcp.metrics import _record_tool_call
from github_mcp.utils import _env_flag

WRITE_ALLOWED = _env_flag("GITHUB_MCP_AUTO_APPROVE", False)
COMPACT_METADATA_DEFAULT = _env_flag("GITHUB_MCP_COMPACT_METADATA", True)

CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)
CONTROLLER_CONTRACT_VERSION = os.environ.get(
    "GITHUB_MCP_CONTROLLER_CONTRACT_VERSION", "2025-03-16"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get(
    "GITHUB_MCP_CONTROLLER_BRANCH", "main"
)

mcp = FastMCP("GitHub Fast MCP")

# Suppress noisy tracebacks when SSE clients disconnect mid-response.
from mcp.shared import session as mcp_shared_session

_orig_send_response = mcp_shared_session.BaseSession._send_response


async def _quiet_send_response(self, request_id, response):
    try:
        return await _orig_send_response(self, request_id, response)
    except ClosedResourceError:
        return None


mcp_shared_session.BaseSession._send_response = _quiet_send_response


async def _github_request(*args, **kwargs):
    client_factory = getattr(sys.modules.get("main"), "_github_client_instance", None)
    kwargs.setdefault("client_factory", client_factory or _github_client_instance)
    return await _http_clients._github_request(*args, **kwargs)


def _summarize_exception(exc: BaseException) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        path = list(exc.path)
        path_display = " → ".join(str(p) for p in path) if path else None
        base_message = exc.message or exc.__class__.__name__
        if path_display:
            return f"{base_message} (at {path_display})"
        return base_message
    return str(exc) or exc.__class__.__name__


def _structured_tool_error(
    exc: BaseException, *, context: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a concise serializable error payload for MCP clients."""

    error: Dict[str, Any] = {
        "error": exc.__class__.__name__,
        "message": _summarize_exception(exc),
        "context": context,
    }
    if path:
        error["path"] = path
    return {"error": error}


def _ensure_write_allowed(context: str) -> None:
    if not WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"MCP write action is temporarily disabled (context: {context})"
        )


_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []


def _find_registered_tool(tool_name: str) -> Optional[tuple[Any, Any]]:
    for tool, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool, "name", None) or getattr(func, "__name__", None)
        if name == tool_name:
            return tool, func
    return None


def _normalize_input_schema(tool: Any) -> Optional[Dict[str, Any]]:
    if tool is None:
        return None

    # Prefer the underlying MCP tool's explicit inputSchema when available.
    raw_schema = getattr(tool, "inputSchema", None)
    if raw_schema is not None:
        if hasattr(raw_schema, "model_dump"):
            return raw_schema.model_dump()
        if isinstance(raw_schema, dict):
            return dict(raw_schema)

    # Fall back to a small set of hand-authored schemas for important tools
    # that do not currently expose an inputSchema via the MCP layer. This
    # keeps describe_tool and validate_tool_args useful without requiring
    # every tool to be fully annotated.
    name = getattr(tool, "name", None)

    if name == "compare_refs":
        return {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
            },
            "required": ["full_name", "base", "head"],
            "additionalProperties": True,
        }

    if name == "list_workflow_runs":
        return {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "branch": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"]},
                "event": {"type": ["string", "null"]},
                "per_page": {"type": "integer", "minimum": 1},
                "page": {"type": "integer", "minimum": 1},
            },
            "required": ["full_name"],
            "additionalProperties": True,
        }

    if name == "list_recent_failures":
        return {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "branch": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["full_name"],
            "additionalProperties": True,
        }

    return None




def _normalize_branch_ref(ref: Optional[str]) -> Optional[str]:
    """Normalize a ref/branch string to a bare branch name when possible.

    This understands common patterns like ``refs/heads/<name>`` but otherwise
    returns the input unchanged so commit SHAs and tags pass through.
    """

    if ref is None:
        return None
    # Strip the common refs/heads/ prefix when present.
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref


def _ensure_write_allowed(context: str, *, target_ref: Optional[str] = None) -> None:
    """Enforce write gating with special handling for the default branch.

    * Unscoped operations (no ``target_ref``) still honor the global
      ``WRITE_ALLOWED`` flag so controllers can fully disable dangerous tools.
    * Writes that explicitly target the controller default branch remain gated
      on ``WRITE_ALLOWED`` so commits to ``main`` (or whatever
      CONTROLLER_DEFAULT_BRANCH is set to) always require an approval call.
    * Writes to non-default branches are allowed even when ``WRITE_ALLOWED`` is
      false so assistants can iterate safely on feature branches.
    """

    # When we do not know which ref a tool will touch, fall back to the global
    # kill switch so destructive tools remain opt-in.
    if target_ref is None:
        if not WRITE_ALLOWED:
            raise WriteNotAuthorizedError(
                "Write-tagged tools are currently disabled for unscoped operations; "
                "call authorize_write_actions to enable them for this session."
            )
        return None

    normalized = _normalize_branch_ref(target_ref)

    # Writes aimed at the controller default branch still require explicit
    # authorization via authorize_write_actions.
    if normalized == CONTROLLER_DEFAULT_BRANCH and not WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"Writes to the controller default branch ({CONTROLLER_DEFAULT_BRANCH}) "
            f"are not yet authorized (context: {context}); call "
            "authorize_write_actions before committing directly to the default branch."
        )

    # Writes to any non-default branch are always allowed from the connector's
    # perspective. Repository protection rules and GitHub permissions still
    # apply server-side.
    return None



def mcp_tool(
    *,
    write_action: bool = False,
    assistant_visible: bool = True,
    **tool_kwargs,
):
    existing_tags = tool_kwargs.pop("tags", None)
    tags: set[str] = set(existing_tags or [])
    if write_action:
        tags.add("write")
    else:
        tags.add("read")

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
    meta = {
        **existing_meta,
        "write_action": write_action,
        "auto_approved": not write_action,
        "assistant_visible": assistant_visible,
    }

    import functools as _functools
    import inspect as _inspect
    import functools as _functools
    import inspect as _inspect

    def decorator(func):
        tool = mcp.tool(
            tags=tags or None,
            meta=meta or None,
            annotations=annotations,
            **tool_kwargs,
        )(func)

        try:
            signature = _inspect.signature(func)
        except (TypeError, ValueError):
            signature = None

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
            elif isinstance(all_args.get("owner"), str) and isinstance(
                all_args.get("repo"), str
            ):
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
            return {
                "repo": repo_full_name,
                "ref": ref,
                "path": path,
                "arg_keys": arg_keys,
            }

        def _result_size_hint(result: Any) -> Optional[int]:
            if isinstance(result, (list, tuple, str)):
                return len(result)
            if isinstance(result, dict):
                return len(result)
            return None

        if asyncio.iscoroutinefunction(func):

            @_functools.wraps(func)
            async def wrapper(*args, **kwargs):
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)
                start = time.perf_counter()

                TOOLS_LOGGER.info(
                    "tool_call_start",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                    },
                )

                errored = False
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        "tool_call_error",
                        extra={
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
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
                TOOLS_LOGGER.info(
                    "tool_call_success",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
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
                start = time.perf_counter()

                TOOLS_LOGGER.info(
                    "tool_call_start",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                    },
                )

                errored = False
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        "tool_call_error",
                        extra={
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
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
                TOOLS_LOGGER.info(
                    "tool_call_success",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
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


__all__ = [
    "COMPACT_METADATA_DEFAULT",
    "CONTROLLER_CONTRACT_VERSION",
    "CONTROLLER_DEFAULT_BRANCH",
    "CONTROLLER_REPO",
    "WRITE_ALLOWED",
    "_find_registered_tool",
    "_github_request",
    "_normalize_input_schema",
    "_structured_tool_error",
    "_ensure_write_allowed",
    "mcp",
    "mcp_tool",
    "register_extra_tools_if_available",
]

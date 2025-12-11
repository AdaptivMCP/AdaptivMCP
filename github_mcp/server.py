"""Shared server setup and decorator utilities for the GitHub MCP."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, Mapping, Optional

import jsonschema
from anyio import ClosedResourceError
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from github_mcp import http_clients as _http_clients
from github_mcp.config import BASE_LOGGER, TOOLS_LOGGER
from github_mcp.exceptions import WriteNotAuthorizedError
from github_mcp.http_clients import _github_client_instance
from github_mcp.metrics import _record_tool_call
from github_mcp.utils import _env_flag, normalize_args
WRITE_ALLOWED = _env_flag("GITHUB_MCP_AUTO_APPROVE", False)
COMPACT_METADATA_DEFAULT = _env_flag("GITHUB_MCP_COMPACT_METADATA", True)

CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get("GITHUB_MCP_CONTROLLER_BRANCH", "main")

mcp = FastMCP("GitHub Fast MCP")

# Suppress noisy tracebacks when SSE clients disconnect mid-response.
from mcp.shared import session as mcp_shared_session  # noqa: E402

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
    """Build a concise serializable error payload for MCP clients.

    This helper also centralizes logging for tool failures so that every
    exception is captured once with enough context for humans to debug,
    without requiring individual tools to sprinkle their own logging.
    """

    message = _summarize_exception(exc)

    # Always log the error once with structured context but without
    # re-raising here. The MCP layer will surface the returned payload
    # to the client.
    BASE_LOGGER.exception(
        "Tool error",
        extra={
            "tool_context": context,
            "tool_error_type": exc.__class__.__name__,
            "tool_error_message": message,
            "tool_error_path": path,
        },
    )

    error: Dict[str, Any] = {
        "error": exc.__class__.__name__,
        "message": message,
        "context": context,
    }
    if path:
        error["path"] = path
    return {"error": error}


def _stringify_annotation(annotation: Any) -> str:
    """Return a deterministic, LLM-friendly description of a parameter type."""

    if annotation is inspect.Signature.empty:
        return "any type"
    if isinstance(annotation, type):
        return annotation.__name__
    if getattr(annotation, "__name__", None):
        return annotation.__name__
    return str(annotation)


def _normalize_tool_description(func, signature: Optional[inspect.Signature], *, llm_level: str) -> str:
    """Flatten docstrings and append explicit usage guidance for the MCP tool."""

    raw_doc = func.__doc__ or ""
    base = " ".join(line.strip() for line in raw_doc.strip().splitlines() if line.strip())
    if not base:
        base = f"{func.__name__} runs the '{func.__name__}' tool logic without extra context."

    param_details: list[str] = []
    if signature is not None:
        for name, param in signature.parameters.items():
            if name in {"self", "cls"}:
                continue
            annotation = _stringify_annotation(param.annotation)
            requirement = "required" if param.default is inspect.Signature.empty else f"default={param.default!r}"
            param_details.append(f"{name} ({annotation}, {requirement})")

    inputs_summary = "Inputs: " + "; ".join(param_details) + "." if param_details else "No parameters are required."
    level_summary = (
        "Classification: advanced tool for mutating operations." if llm_level == "advanced" else "Classification: low-level read-focused tool."
    )

    return f"{base} {inputs_summary} {level_summary}"


def _ensure_write_allowed(context: str) -> None:
    if not WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"MCP write action is temporarily disabled (context: {context})"
        )


_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []


def _preflight_tool_args(tool: Any, raw_args: Mapping[str, Any]) -> None:
    """Validate a tool call's arguments against its input schema when available."""

    try:
        normalized_args = normalize_args(raw_args)
    except Exception as exc:  # extremely defensive - surface as a validation failure
        raise jsonschema.ValidationError(str(exc)) from exc

    schema = _normalize_input_schema(tool)
    if schema is None:
        # When no schema is published we deliberately skip strict validation so
        # tools without schemas continue to work as before.
        return None

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(normalized_args), key=str)
    if not errors:
        return None

    primary = errors[0]
    primary.context = list(errors[1:])
    raise primary
def _find_registered_tool(tool_name: str) -> Optional[tuple[Any, Any]]:
    for tool, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool, "name", None) or getattr(func, "__name__", None)
        if name == tool_name:
            return tool, func
    return None


def _normalize_input_schema(tool: Any) -> Optional[Dict[str, Any]]:
    if tool is None:
        return None

    name = getattr(tool, "name", None)

    # A small set of tools have richer controller-level semantics (e.g.
    # ref-defaulting, list vs. scalar arguments, or controller-managed
    # validation flows) that do not map cleanly onto the auto-generated MCP
    # JSON Schemas. For these we deliberately skip strict preflight and rely on
    # their existing runtime validation and the test suite instead.
    if name in {
        "run_command",
        "commit_workspace_files",
        "cache_files",
        "fetch_files",
        "update_files_and_open_pr",
        "create_issue",
        "update_issue",
        "describe_tool",
        "validate_tool_args",
        "list_recent_failures",
    }:
        return None

    # Prefer the underlying MCP tool's explicit inputSchema when available.
    raw_schema = getattr(tool, "inputSchema", None)
    schema: Optional[Dict[str, Any]] = None
    if raw_schema is not None:
        # FastMCP tools typically expose a Pydantic model here.
        if hasattr(raw_schema, "model_dump"):
            schema = raw_schema.model_dump()
        elif isinstance(raw_schema, dict):
            schema = dict(raw_schema)

    # that do not currently expose an inputSchema via the MCP layer. This
    # keeps describe_tool and validate_tool_args useful without requiring
    # every tool to be fully annotated.
    if schema is None:
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
                    "limit": {"type": "integer"},
                },
                "required": ["full_name"],
                "additionalProperties": True,
            }

    # At this point we have either a concrete schema from the MCP layer or
    # None. When a schema is present, we sometimes need to tweak it slightly
    # for backwards compatibility with the controller's expectations.
    if schema is not None:
        props = schema.setdefault("properties", {})

        # run_command: allow ref to be string or null so callers can pass
        # None and rely on controller defaults without tripping JSON Schema.
        if name == "run_command":
            ref_prop = props.get("ref")
            if isinstance(ref_prop, dict):
                existing_type = ref_prop.get("type")
                if isinstance(existing_type, str):
                    if existing_type != "null":
                        ref_prop["type"] = sorted({existing_type, "null"})
                elif isinstance(existing_type, list):
                    if "null" not in existing_type:
                        ref_prop["type"] = sorted(set(existing_type + ["null"]))

        # commit_workspace_files: files should be a list of strings.
        if name == "commit_workspace_files":
            files_prop = props.get("files")
            if isinstance(files_prop, dict):
                files_prop["type"] = "array"
                files_prop["items"] = {"type": "string"}

        # cache_files / fetch_files: paths should be a list of strings.
        if name in {"cache_files", "fetch_files"}:
            paths_prop = props.get("paths")
            if isinstance(paths_prop, dict):
                paths_prop["type"] = "array"
                paths_prop["items"] = {"type": "string"}

        # update_files_and_open_pr: files should be a list of objects.
        if name == "update_files_and_open_pr":
            files_prop = props.get("files")
            if isinstance(files_prop, dict):
                files_prop["type"] = "array"
                files_prop["items"] = {"type": "object"}

        # create_issue / update_issue: labels and assignees should allow lists
        # of strings as well as null. update_issue.state should allow string
        # so the tool can enforce allowed values itself.
        if name in {"create_issue", "update_issue"}:
            for key in ("labels", "assignees"):
                prop = props.get(key)
                if isinstance(prop, dict):
                    existing_type = prop.get("type")
                    types: set[str] = set()
                    if isinstance(existing_type, str):
                        types.add(existing_type)
                    elif isinstance(existing_type, list):
                        types.update(existing_type)
                    if not types:
                        types.add("null")
                    types.add("array")
                    prop["type"] = sorted(types)
                    prop["items"] = {"type": "string"}

            if name == "update_issue":
                state_prop = props.get("state")
                if isinstance(state_prop, dict):
                    existing_type = state_prop.get("type")
                    types: set[str] = set()
                    if isinstance(existing_type, str):
                        types.add(existing_type)
                    elif isinstance(existing_type, list):
                        types.update(existing_type)
                    types.update({"string", "null"})
                    state_prop["type"] = sorted(types)

        # describe_tool: names can be string, array of strings, or null.
        if name == "describe_tool":
            names_prop = props.get("names")
            if isinstance(names_prop, dict):
                existing_type = names_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"string", "array", "null"})
                names_prop["type"] = sorted(types)
                names_prop["items"] = {"type": "string"}

        # validate_tool_args: payload should allow objects; tool_names should
        # allow a list of strings as well as null.
        if name == "validate_tool_args":
            payload_prop = props.get("payload")
            if isinstance(payload_prop, dict):
                existing_type = payload_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"object", "null"})
                payload_prop["type"] = sorted(types)

            tool_names_prop = props.get("tool_names")
            if isinstance(tool_names_prop, dict):
                existing_type = tool_names_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"array", "string", "null"})
                tool_names_prop["type"] = sorted(types)
                tool_names_prop["items"] = {"type": "string"}

        # list_recent_failures: if the MCP schema provided a minimum on limit,
        # drop it so the tool's own ValueError semantics are preserved.
        if name == "list_recent_failures":
            limit_prop = props.get("limit")
            if isinstance(limit_prop, dict):
                limit_prop.pop("minimum", None)

        return schema

    # As a final fallback, derive a best-effort JSON schema from the
    # registered function's Python signature so that describe_tool and
    # list_all_actions can still surface argument names and a reasonable
    # required/optional split even when the MCP layer does not publish an
    # explicit inputSchema.
    try:
        import inspect as _inspect
    except Exception:  # extremely defensive
        return None

    try:
        # Find the Python function associated with this tool so we can inspect
        # its signature.
        for registered_tool, func in _REGISTERED_MCP_TOOLS:
            if registered_tool is not tool:
                continue

            try:
                target_func = _inspect.unwrap(func)
                sig = _inspect.signature(target_func)
            except (TypeError, ValueError):
                return None

            properties: Dict[str, Any] = {}
            required: list[str] = []

            def _annotation_to_json_types(ann: Any) -> Optional[list[str]]:
                # Handle typing.Optional / Union[...] by unwrapping None.
                origin = getattr(ann, "__origin__", None)
                args = getattr(ann, "__args__", ()) or ()
                if origin is not None and args:
                    optional = any(a is type(None) for a in args)  # noqa: E721
                    json_types: list[str] = []
                    for arg in args:
                        if arg is type(None):  # noqa: E721
                            continue
                        nested = _annotation_to_json_types(arg)
                        if nested is None:
                            continue
                        if isinstance(nested, list):
                            json_types.extend(nested)
                        else:
                            json_types.append(nested)

                    if not json_types and optional:
                        return ["null"]
                    if optional:
                        json_types.append("null")
                    return sorted(set(json_types)) if json_types else None

                if ann in (str, bytes):
                    return ["string"]
                if ann is int:
                    return ["integer"]
                if ann is float:
                    return ["number"]
                if ann is bool:
                    return ["boolean"]
                if ann in (list, tuple, set):
                    return ["array"]
                if ann is dict:
                    return ["object"]
                return None

            for param_name, param in sig.parameters.items():
                if param.kind in (
                    _inspect.Parameter.VAR_POSITIONAL,
                    _inspect.Parameter.VAR_KEYWORD,
                ):
                    # *args / **kwargs do not map cleanly to JSON object
                    # properties; skip them for the best-effort schema.
                    continue
                if param_name in ("self", "cls"):
                    continue

                prop: Dict[str, Any] = {}

                if param.annotation is not _inspect._empty:
                    json_types = _annotation_to_json_types(param.annotation)
                    if json_types:
                        if len(json_types) == 1:
                            prop["type"] = json_types[0]
                        else:
                            prop["type"] = json_types

                if param.default is _inspect._empty:
                    required.append(param_name)
                else:
                    # Defaults are helpful hints but may not always be
                    # JSON-serializable; they are included on a best-effort
                    # basis only.
                    prop["default"] = param.default

                    if "type" in prop and param.default is None:
                        type_value = prop["type"]
                        if isinstance(type_value, list):
                            if "null" not in type_value:
                                prop["type"] = sorted(set(type_value + ["null"]))
                        elif isinstance(type_value, str) and type_value != "null":
                            prop["type"] = sorted({type_value, "null"})

                properties[param_name] = prop

            if not properties and not required:
                return None

            return {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": True,
            }
    except Exception:  # extremely defensive
        return None

    return None
            schema: Dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
            schema["additionalProperties"] = True
            return schema
    except Exception:
        # Extremely defensive: if anything goes wrong during introspection,
        # fall back to having no schema rather than throwing.
        return None

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
        return ref[len("refs/heads/") :]
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
    }

    import functools as _functools
    import inspect as _inspect

    def decorator(func):
        signature = None
        try:
            signature = _inspect.signature(func)
        except (TypeError, ValueError):
            signature = None

        normalized_description = _normalize_tool_description(
            func, signature, llm_level=llm_level
        )
        tool_kwargs.setdefault("description", normalized_description)
        func.__doc__ = normalized_description

        tool = mcp.tool(
            tags=tags or None,
            meta=meta or None,
            annotations=annotations,
            **tool_kwargs,
        )(func)

        def _format_args_for_log(all_args: Mapping[str, Any], *, limit: int = 1200) -> str:
            """Return a human-friendly, truncated snapshot of the tool arguments."""

            if not all_args:
                return "<no args>"

            try:
                preview = json.dumps(all_args, default=str, ensure_ascii=False)
            except Exception:
                preview = repr(all_args)

            if len(preview) > limit:
                preview = f"{preview[:limit]}… (+{len(preview) - limit} chars)"

            return preview

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
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)
                start = time.perf_counter()

                # Preflight validation of arguments against the tool's declared
                # input schema, similar to validate_tool_args but applied
                # automatically for every call.
                _preflight_tool_args(tool, context.get("_all_args", {}))
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
                start = time.perf_counter()

                # Preflight validation of arguments against the tool's declared
                # input schema, similar to validate_tool_args but applied
                # automatically for every call.
                _preflight_tool_args(tool, context.get("_all_args", {}))
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


__all__ = [
    "COMPACT_METADATA_DEFAULT",
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

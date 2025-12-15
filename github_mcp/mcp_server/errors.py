from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

import jsonschema

from github_mcp.config import BASE_LOGGER
from github_mcp.exceptions import WriteNotAuthorizedError

def _summarize_exception(exc: BaseException) -> str:
    if isinstance(exc, jsonschema.ValidationError):
        path = list(exc.path)
        path_display = " → ".join(str(p) for p in path) if path else None
        base_message = exc.message or exc.__class__.__name__
        if path_display:
            return f"{base_message} (at {path_display})"
        return base_message
    return str(exc) or exc.__class__.__name__


_OPENAI_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"blocked by openai", re.IGNORECASE),
    re.compile(r"couldn['’]?t determine the safety status", re.IGNORECASE),
    re.compile(r"could not determine the safety status", re.IGNORECASE),
)


def _classify_tool_error_origin(message: str) -> str:
    """Best-effort attribution for a tool failure.

    - openai_platform: blocked/failed before reaching the controller.
    - adaptiv_controller: failure inside the controller (validation, timeout, GitHub API, etc.).

    The controller cannot see true upstream blocks that prevent the tool call from
    being invoked at all, but it can still label errors when those upstream messages
    are surfaced as strings.
    """

    if not isinstance(message, str):
        return "adaptiv_controller"
    for pat in _OPENAI_BLOCK_PATTERNS:
        if pat.search(message):
            return "openai_platform"
    return "adaptiv_controller"


def _classify_tool_error_category(exc: BaseException, message: str) -> str:
    if isinstance(exc, WriteNotAuthorizedError):
        return "write_not_authorized"
    if isinstance(exc, jsonschema.ValidationError) or isinstance(exc, ValueError):
        return "validation"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    lowered = (message or "").lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if exc.__class__.__name__ in {"GitHubAPIError", "GitHubAuthError", "GitHubRateLimitError"}:
        return "github_api"
    return "unknown"


def _tool_error_next_steps(*, context: str, origin: str, category: str) -> list[dict[str, Any]]:
    def mk(kind: str, **kwargs: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "kind": kind,
            "actor": "assistant",
            "user_can_invoke_tools": False,
        }
        base.update(kwargs)
        return base

    steps: list[dict[str, Any]] = []

    if origin == "openai_platform":
        steps.append(
            mk(
                "openai",
                action=(
                    "Assistant: this tool call was blocked upstream by OpenAI before it reached the Adaptiv controller."
                    "Do NOT include token-like strings (e.g., PAT formats) in tool inputs or command strings; use placeholders like <REDACTED>."
                ),
                what_to_do=(
                    "Assistant: rephrase the tool call to comply with OpenAI tool rules. "
                    "If it is still blocked, use the workspace fallback tool for this operation. "
                    "Do not ask the user to run controller tools."
                ),
            )
        )

        if context in {"create_branch", "ensure_branch"}:
            steps.append(
                mk(
                    "workspace_fallback",
                    tool="workspace_create_branch",
                    action=(
                        "Assistant: create the branch using workspace git (workspace_create_branch) instead of the GitHub API tool."
                    ),
                )
            )

        if context in {
            "create_pull_request",
            "open_pr_for_existing_branch",
            "update_files_and_open_pr",
        }:
            steps.append(
                mk(
                    "workspace_fallback",
                    tool="run_command",
                    action=(
                        "Assistant: create the PR from the workspace using run_command (GitHub API call via python/curl)."
                    ),
                )
            )

        return steps

    # Controller-origin errors.
    steps.append(
        mk(
            "controller",
            action="Assistant: the failure occurred inside the Adaptiv controller (tool execution).",
        )
    )

    if category == "validation":
        steps.append(
            mk(
                "args",
                tool="describe_tool",
                action=(
                    "Assistant: validate tool parameters with describe_tool (or validate_tool_args) and retry."
                ),
            )
        )

    if category == "timeout":
        steps.append(
            mk(
                "timeout",
                tool="run_command",
                action=(
                    "Assistant: retry with a higher timeout_seconds or split into smaller steps "
                    "(workspace run_command is best for long operations)."
                ),
            )
        )

    # Context-specific guidance to reduce repeated confusion.
    if context in {"create_branch", "ensure_branch"}:
        steps.append(
            mk(
                "hint",
                action=(
                    "Assistant: if branch creation is blocked upstream, use workspace_create_branch instead of create_branch. Avoid token-like strings in tool inputs; use <REDACTED> placeholders."
                ),
            )
        )

    if context in {
        "create_pull_request",
        "open_pr_for_existing_branch",
        "update_files_and_open_pr",
    }:
        steps.append(
            mk(
                "hint",
                action=(
                    "Assistant: if PR creation is blocked upstream, use run_command in the workspace to call the GitHub PR API. Avoid token-like strings in tool inputs; use <REDACTED> placeholders."
                ),
            )
        )

    return steps

    # Controller-origin errors.
    steps.append(
        {
            "kind": "controller",
            "actor": "assistant",
            "user_can_invoke_tools": False,
            "action": "Assistant: the failure occurred inside the Adaptiv controller (tool execution).",
        }
    )

    if category == "validation":
        steps.append(
            {
                "kind": "args",
                "actor": "assistant",
                "user_can_invoke_tools": False,
                "tool": "describe_tool",
                "action": "Assistant: validate tool parameters with describe_tool (or validate_tool_args) and retry.",
            }
        )

    if category == "timeout":
        steps.append(
            {
                "kind": "timeout",
                "actor": "assistant",
                "user_can_invoke_tools": False,
                "tool": "run_command",
                "action": "Assistant: retry with a higher timeout_seconds or split into smaller steps (workspace run_command is best for long operations).",
            }
        )

    # Context-specific guidance to reduce repeated confusion.
    if context in {"create_branch", "ensure_branch"}:
        steps.append(
            {
                "kind": "hint",
                "actor": "assistant",
                "user_can_invoke_tools": False,
                "action": "Assistant: if branch creation is blocked upstream, use workspace_create_branch instead of create_branch. Avoid token-like strings in tool inputs; use <REDACTED> placeholders.",
            }
        )
    if context in {
        "create_pull_request",
        "open_pr_for_existing_branch",
        "update_files_and_open_pr",
    }:
        steps.append(
            {
                "kind": "hint",
                "actor": "assistant",
                "user_can_invoke_tools": False,
                "action": "Assistant: if PR creation is blocked upstream, use run_command in the workspace to call the GitHub PR API. Avoid token-like strings in tool inputs; use <REDACTED> placeholders.",
            }
        )

    return steps


def _structured_tool_error(
    exc: BaseException, *, context: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a concise serializable error payload for MCP clients.

    This helper also centralizes logging for tool failures so that every
    exception is captured once with enough context for humans to debug,
    without requiring individual tools to sprinkle their own logging.

    In addition to a short message, the payload includes:
      - origin: openai_platform vs adaptiv_controller
      - category: validation/timeout/github_api/etc.
      - next_steps: actionable recovery guidance (often: use workspace tools)
    """

    message = _summarize_exception(exc)
    origin = _classify_tool_error_origin(message)
    category = _classify_tool_error_category(exc, message)

    if origin == "openai_platform":
        category = "openai_block"

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
            "tool_error_origin": origin,
            "tool_error_category": category,
        },
    )

    error: Dict[str, Any] = {
        "error": exc.__class__.__name__,
        "message": message,
        "context": context,
        "origin": origin,
        "category": category,
        "actor": "assistant",
        "user_can_invoke_tools": False,
        "next_steps": _tool_error_next_steps(context=context, origin=origin, category=category),
    }
    if path:
        error["path"] = path
    return {"error": error}

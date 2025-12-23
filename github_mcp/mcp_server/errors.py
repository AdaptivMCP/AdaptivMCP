from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import jsonschema

from github_mcp.config import BASE_LOGGER
from github_mcp.exceptions import WriteApprovalRequiredError, WriteNotAuthorizedError
from github_mcp.redaction import redact_text
from github_mcp.mcp_server.context import WRITE_ALLOWED


@dataclass(frozen=True)
class ToolInputValidationError(ValueError):
    """Raised when tool inputs fail controller-side validation."""

    tool_name: str
    message: str
    field: str | None = None

    def __str__(self) -> str:  # pragma: no cover
        if self.field:
            return f"{self.tool_name}: {self.message} (field={self.field})"
        return f"{self.tool_name}: {self.message}"


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
    """Best-effort attribution for a tool failure."""

    if not isinstance(message, str):
        return "adaptiv_controller"
    for pat in _OPENAI_BLOCK_PATTERNS:
        if pat.search(message):
            return "openai_platform"
    return "adaptiv_controller"


def _classify_tool_error_category(exc: BaseException, message: str) -> str:
    if isinstance(exc, WriteApprovalRequiredError):
        return "write_approval_required"
    if isinstance(exc, WriteNotAuthorizedError):
        return "write_not_authorized"
    if isinstance(exc, (jsonschema.ValidationError, ToolInputValidationError, ValueError)):
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
                    "Assistant: this tool call was blocked upstream by OpenAI before it reached the Adaptiv controller. "
                    "Do NOT include token-like strings in tool inputs; use placeholders like <REDACTED>."
                ),
                what_to_do=(
                    "Assistant: Do not ask the user to change anything. Rephrase the tool call to comply with OpenAI tool rules. "
                    "If it is still blocked, use the workspace fallback tool for this operation."
                ),
            )
        )

        if context in {"create_branch", "ensure_branch"}:
            steps.append(
                mk(
                    "workspace_fallback",
                    tool="workspace_create_branch",
                    action="Assistant: create the branch using workspace git (workspace_create_branch) instead of the GitHub API tool.",
                )
            )

        if context in {"create_pull_request", "open_pr_for_existing_branch", "update_files_and_open_pr"}:
            steps.append(
                mk(
                    "workspace_fallback",
                    tool="run_command",
                    action="Assistant: create the PR from the workspace using run_command (GitHub API call via python/curl).",
                )
            )

        return steps

    if category == "write_approval_required":
        steps.append(
            mk(
                "approval",
                action=(
                    "Assistant: this operation needs approval. Call authorize_write_actions(approved=true) before retrying the tool."
                ),
            )
        )

        return steps

    # Controller-origin errors.
    steps.append(mk("controller", action="Assistant: the failure occurred inside the Adaptiv controller (tool execution)."))

    if category == "validation":
        steps.append(
            mk(
                "args",
                tool="describe_tool",
                action="Assistant: validate tool parameters with describe_tool (or validate_tool_args) and retry.",
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

    if context in {"create_branch", "ensure_branch"}:
        steps.append(
            mk(
                "hint",
                action=(
                    "Assistant: if branch creation is blocked upstream, use workspace_create_branch instead of create_branch. "
                    "Avoid token-like strings in tool inputs; use <REDACTED> placeholders."
                ),
            )
        )

    if context in {"create_pull_request", "open_pr_for_existing_branch", "update_files_and_open_pr"}:
        steps.append(
            mk(
                "hint",
                action=(
                    "Assistant: if PR creation is blocked upstream, use run_command in the workspace to call the GitHub PR API. "
                    "Avoid token-like strings in tool inputs; use <REDACTED> placeholders."
                ),
            )
        )

    return steps


def _structured_tool_error(
    exc: BaseException, *, context: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a concise serializable error payload for MCP clients."""

    message = _summarize_exception(exc)
    message = redact_text(message)
    origin = _classify_tool_error_origin(message)
    category = _classify_tool_error_category(exc, message)

    if origin == "openai_platform":
        category = "openai_block"

    BASE_LOGGER.exception(
        "Tool error",
        extra={
            "tool_context": context,
            "tool_error_type": exc.__class__.__name__,
            "tool_error_message": message,
            "tool_error_path": path,
            "tool_error_origin": origin,
            "tool_error_category": category,
            "tool_write_allowed": WRITE_ALLOWED,
        },
    )

    error: Dict[str, Any] = {
        "error": exc.__class__.__name__,
        "message": message,
        "context": context,
        "origin": origin,
        "category": category,
        "write_allowed": WRITE_ALLOWED,
        "actor": "assistant",
        "user_can_invoke_tools": False,
        "next_steps": _tool_error_next_steps(context=context, origin=origin, category=category),
    }
    if getattr(exc, "code", None):
        error["code"] = getattr(exc, "code")
    if isinstance(exc, WriteApprovalRequiredError):
        error["approval_required"] = True
    if getattr(exc, "write_gate", None):
        error["write_gate"] = getattr(exc, "write_gate")
    if path:
        error["path"] = path
    return {"error": error}

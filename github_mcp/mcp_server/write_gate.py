"""Write authorization gate and enforcement helpers.

MCP server framework: tool registry, schemas, context, and write gating.
"""

from __future__ import annotations

from typing import Literal, Optional


def _server():
    from github_mcp import server as _server_mod

    return _server_mod


def _ensure_write_allowed(
    context: str,
    *,
    target_ref: Optional[str] = None,
    intent: Literal["write", "push", "web", "pr", "non_harm"] = "write",
) -> None:
    """Surface the write gate policy without hard-blocking tool calls.

    The connector UI is responsible for prompting/approval. This helper should
    never block a tool call outright; it only preserves the policy surface so
    tests and tooling continue to exercise the expected code paths.

    Policy summary:
    * Write-tagged tools are expected to prompt unless explicitly approved via
      the write gate. Non-harmful metadata edits remain prompt-free.
    * PR flows are never write-gated.
    """

    # Non-harmful changes and PR metadata edits are always allowed.
    if intent in {"pr", "non_harm"}:
        return None

    return None

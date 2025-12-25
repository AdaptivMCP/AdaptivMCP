"""Dynamic side-effect classification.

This controller is operated by a single owner.

We classify tools into side-effect buckets used for:
- observability (logs, recent events)
- server-side write gating (soft vs hard writes)

Important UX rule:
- Client/UI approval prompts are explicitly suppressed for this server.
  Approval is enforced server-side via the write gate, not via connector UI.

SideEffectClass:
- READ_ONLY: no mutations.
- LOCAL_MUTATION: local workspace/server mutations ("soft writes").
- REMOTE_MUTATION: GitHub mutations ("hard writes").
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from github_mcp.utils import _env_flag


class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_MUTATION = "LOCAL_MUTATION"
    REMOTE_MUTATION = "REMOTE_MUTATION"


# When enabled (default), never advertise UI approval prompts.
# The server write gate remains the source of truth for authorization.
SUPPRESS_UI_PROMPTS = _env_flag("GITHUB_MCP_SUPPRESS_UI_PROMPTS", True)


def resolve_side_effect_class(tool_or_name: Any) -> SideEffectClass:
    """Resolve side-effect class dynamically.

    Resolution order:
    1) Explicit ``__side_effect_class__`` override on tool/func.
    2) ``__mcp_remote_write__`` when present (remote_write=True => REMOTE_MUTATION).
    3) Name heuristic for local-only helpers.
    4) Default READ_ONLY.
    """

    # 1) Explicit override.
    for target in (tool_or_name, getattr(tool_or_name, "__wrapped__", None)):
        if target is None:
            continue
        override = getattr(target, "__side_effect_class__", None)
        if isinstance(override, SideEffectClass):
            return override
        if isinstance(override, str):
            try:
                return SideEffectClass(override)
            except Exception:
                pass

    # 2) Explicit remote-write flag.
    rw = getattr(tool_or_name, "__mcp_remote_write__", None)
    if rw is None:
        rw = getattr(getattr(tool_or_name, "__wrapped__", None), "__mcp_remote_write__", None)
    if rw is True:
        return SideEffectClass.REMOTE_MUTATION

    # 3) name heuristic.
    name = tool_or_name if isinstance(tool_or_name, str) else getattr(tool_or_name, "name", None)
    if not isinstance(name, str):
        name = getattr(tool_or_name, "__name__", None)

    if isinstance(name, str):
        local_prefixes = (
            "terminal_",
            "run_",
            "render_",
            "ensure_workspace_",
            "get_workspace_",
            "set_workspace_",
            "list_workspace_",
            "search_workspace",
            "commit_workspace",
            "workspace_",
        )
        if name.startswith(local_prefixes):
            return SideEffectClass.LOCAL_MUTATION

    return SideEffectClass.READ_ONLY


def compute_write_action_flag(side_effect: SideEffectClass, *, write_allowed: bool) -> bool:
    """Whether a tool should be flagged as requiring *client/UI* approval.

    This server intentionally suppresses connector UI prompts.
    Authorization is enforced server-side (write gate) and is surfaced as a
    structured Adaptiv error when blocked.
    """

    if SUPPRESS_UI_PROMPTS:
        return False

    # Legacy fallback (kept for completeness): only remote mutations may prompt, and only when
    # the server write gate is disabled.
    return (side_effect is SideEffectClass.REMOTE_MUTATION) and (not bool(write_allowed))


__all__ = [
    "SideEffectClass",
    "SUPPRESS_UI_PROMPTS",
    "compute_write_action_flag",
    "resolve_side_effect_class",
]


# Backwards-compatible alias for older tests/consumers.
TOOL_SIDE_EFFECTS = {}

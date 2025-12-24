from __future__ import annotations

"""Dynamic side-effect classification.

This controller is operated by a single owner.

We avoid a static tool-name map; instead, classification is derived from tool
registration attributes (preferred) and lightweight heuristics.

SideEffectClass:
- READ_ONLY: no mutations.
- LOCAL_MUTATION: local workspace/server mutations ("soft writes").
- REMOTE_MUTATION: GitHub mutations ("hard writes").

Important UX rule:
- Only REMOTE_MUTATION should trigger the connector UI approval prompt.
  Soft-write approval is enforced server-side via the write gate.
"""

from enum import Enum
from typing import Any


class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_MUTATION = "LOCAL_MUTATION"
    REMOTE_MUTATION = "REMOTE_MUTATION"


def resolve_side_effect_class(tool_or_name: Any) -> SideEffectClass:
    """Resolve side-effect class dynamically.

    Resolution order:
    1) Explicit ``__side_effect_class__`` override on tool/func.
    2) ``__mcp_write_action__`` when present (write_action=True => REMOTE_MUTATION).
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

    # 2) write_action flag.
    wa = getattr(tool_or_name, "__mcp_write_action__", None)
    if wa is None:
        wa = getattr(getattr(tool_or_name, "__wrapped__", None), "__mcp_write_action__", None)
    if wa is True:
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
    """Whether the tool should be flagged as requiring connector UI approval."""

    # Only hard writes (remote GitHub mutations) should prompt.
    return side_effect is SideEffectClass.REMOTE_MUTATION


__all__ = [
    "SideEffectClass",
    "compute_write_action_flag",
    "resolve_side_effect_class",
]


# Backwards-compatible alias for older tests/consumers.
TOOL_SIDE_EFFECTS = {}

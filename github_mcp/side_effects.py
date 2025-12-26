"""Dynamic side-effect classification.

This controller is operated by a single owner.

We classify tools into side-effect buckets used for:
- observability (logs, recent events)
- server-side write gating (soft vs hard writes)

UX policy:
- Client/UI approval prompts are never used by this server.
  Authorization is enforced server-side via the write gate.

SideEffectClass:
- READ_ONLY: no mutations.
- LOCAL_MUTATION: local workspace/server mutations ("soft writes").
- REMOTE_MUTATION: GitHub mutations ("hard writes").
"""

from __future__ import annotations

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
    2) ``__mcp_remote_write__`` when present (remote_write=True => REMOTE_MUTATION).
    3) Name heuristic for web and local-only helpers.
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

    # 3) Name heuristic.
    name = tool_or_name if isinstance(tool_or_name, str) else getattr(tool_or_name, "name", None)
    if not isinstance(name, str):
        name = getattr(tool_or_name, "__name__", None)

    if isinstance(name, str):
        if name == "fetch_url" or name.startswith("web_"):
            return SideEffectClass.REMOTE_MUTATION
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


__all__ = ["SideEffectClass", "resolve_side_effect_class"]

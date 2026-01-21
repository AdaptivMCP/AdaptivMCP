from __future__ import annotations

import re
from typing import Any

_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _registered_tool_name(tool: Any, func: Any) -> str | None:
    name = getattr(tool, "name", None)
    if name:
        return str(name)

    name = getattr(func, "__mcp_tool_name__", None)
    if name:
        return str(name)

    name = getattr(func, "__name__", None)
    if name:
        return str(name)

    name = getattr(tool, "__name__", None)
    if name:
        return str(name)

    return None


def _tool_name_variants(tool_name: str) -> list[str]:
    """Generate common variants of a tool name produced by LLMs/clients.

    We see several common failure modes in the wild:
    - Leading slashes ("/terminal_command")
    - Hyphenated names ("terminal-command")
    - Module-qualified names ("github_mcp.workspace_tools.git_ops.workspace_sync_to_remote")

    This helper intentionally does *not* do any expensive fuzzy matching.
    """

    if not tool_name:
        return []

    raw = str(tool_name).strip()
    if not raw:
        return []

    variants: set[str] = {raw}
    variants.add(raw.strip("/"))

    # If the caller mistakenly includes a URL-ish prefix, keep the last segment.
    if "/" in raw:
        variants.add(raw.rsplit("/", 1)[-1])

    # If the caller includes a dotted module path, keep the last component.
    if "." in raw:
        variants.add(raw.rsplit(".", 1)[-1])

    # Some clients accidentally include both; normalize them too.
    for candidate in list(variants):
        if "/" in candidate:
            variants.add(candidate.rsplit("/", 1)[-1])
        if "." in candidate:
            variants.add(candidate.rsplit(".", 1)[-1])

    # Stable order for tests/debugging.
    return sorted(variants)


def _canonicalize_tool_name(tool_name: str) -> str:
    """Canonicalize a tool name for forgiving comparisons.

    This is intentionally *lossy*:
    - Lower-cases
    - Converts camelCase -> snake_case
    - Treats hyphens/spaces as underscores
    - Collapses repeated underscores

    It is used as a fallback when an exact name match fails.
    """

    token = str(tool_name or "").strip().strip("/")
    if not token:
        return ""

    # If a module path is provided, canonicalize only the final component.
    if "." in token:
        token = token.rsplit(".", 1)[-1]

    token = _CAMEL_BOUNDARY_RE.sub("_", token)
    token = token.replace("-", "_").replace(" ", "_")
    token = _MULTI_UNDERSCORE_RE.sub("_", token)
    token = token.strip("_").lower()
    return token


def _find_registered_tool(tool_name: str) -> tuple[Any, Any] | None:
    # 1) Exact match (fast path).
    for candidate in _tool_name_variants(tool_name):
        for tool, func in _REGISTERED_MCP_TOOLS:
            name = _registered_tool_name(tool, func)
            if name == candidate:
                return tool, func

    # 2) Case-insensitive match (common when callers preserve casing).
    for candidate in _tool_name_variants(tool_name):
        candidate_lower = candidate.lower()
        for tool, func in _REGISTERED_MCP_TOOLS:
            name = _registered_tool_name(tool, func)
            if name and name.lower() == candidate_lower:
                return tool, func

    # 3) Canonicalized match (hyphens, camelCase, etc.).
    candidates: list[tuple[Any, Any]] = []
    canon_inputs = {c: _canonicalize_tool_name(c) for c in _tool_name_variants(tool_name)}
    canon_inputs = {k: v for k, v in canon_inputs.items() if v}

    if not canon_inputs:
        return None

    for tool, func in _REGISTERED_MCP_TOOLS:
        name = _registered_tool_name(tool, func)
        if not name:
            continue
        canon_name = _canonicalize_tool_name(name)
        if not canon_name:
            continue
        if canon_name in canon_inputs.values():
            candidates.append((tool, func))

    # If the canonical match is ambiguous, prefer to fail with suggestions
    # rather than silently choosing the wrong tool.
    if len(candidates) == 1:
        return candidates[0]

    return None

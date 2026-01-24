from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from github_mcp.config import SERVER_GIT_COMMIT
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS

_ANCHOR_LOCK = threading.Lock()
_ANCHOR_CACHE: tuple[str, dict[str, Any]] | None = None


def _registered_tool_name(tool: Any, func: Any) -> str:
    for candidate in (
        getattr(tool, "name", None),
        getattr(func, "__mcp_tool_name__", None),
        getattr(func, "__name__", None),
        getattr(tool, "__name__", None),
    ):
        if candidate:
            return str(candidate)
    return "unknown"


def _is_write_action(tool_obj: Any, func: Any) -> bool:
    value = getattr(func, "__mcp_write_action__", None)
    if value is None:
        value = getattr(tool_obj, "write_action", None)
    if value is None:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            value = meta.get("write_action")
    return bool(value)


def build_server_anchor_payload() -> dict[str, Any]:
    """Return a deterministic payload that identifies the deployed tool surface.

    This is designed to help clients detect "drift" (server redeploys / tool
    schema changes) and to aid reconnection logic. It is not security material.
    """

    tools = []
    for tool_obj, func in list(_REGISTERED_MCP_TOOLS):
        name = _registered_tool_name(tool_obj, func)
        schema_hash = getattr(func, "__mcp_input_schema_hash__", None)
        tools.append(
            {
                "name": name,
                "schema_hash": str(schema_hash) if schema_hash else None,
                "write_action": _is_write_action(tool_obj, func),
            }
        )

    tools.sort(key=lambda t: t.get("name") or "")

    return {
        "git_commit": SERVER_GIT_COMMIT,
        "tools": tools,
    }


def get_server_anchor(*, refresh: bool = False) -> tuple[str, dict[str, Any]]:
    """Return (anchor, payload) for the current process.

    Anchor is a stable SHA-256 hash over a canonical JSON representation of the
    tool surface + server git commit.
    """

    global _ANCHOR_CACHE

    if _ANCHOR_CACHE is not None and not refresh:
        return _ANCHOR_CACHE

    with _ANCHOR_LOCK:
        if _ANCHOR_CACHE is not None and not refresh:
            return _ANCHOR_CACHE

        payload = build_server_anchor_payload()
        blob = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        anchor = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        _ANCHOR_CACHE = (anchor, payload)
        return _ANCHOR_CACHE


def anchor_matches(value: str | None) -> bool:
    if not value:
        return False
    anchor, _payload = get_server_anchor()
    return str(value).strip() == anchor


def normalize_anchor(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None

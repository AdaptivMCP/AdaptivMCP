"""Minimal error helpers.

Return raw exception messages without redaction or structured envelopes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _structured_tool_error(
    exc: BaseException,
    *,
    context: Optional[str] = None,
    path: Optional[str] = None,
    tool_descriptor: Optional[Dict[str, Any]] = None,
    tool_descriptor_text: Optional[str] = None,
    tool_surface: Optional[str] = None,
    routing_hint: Optional[Dict[str, Any]] = None,
    request: Optional[Dict[str, Any]] = None,
    trace: Optional[Dict[str, Any]] = None,
    args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _ = context, path, tool_descriptor, tool_descriptor_text, tool_surface, routing_hint, request
    _ = trace, args
    return {"error": str(exc)}

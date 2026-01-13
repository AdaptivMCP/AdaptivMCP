"""
Raw error model for Adaptiv MCP.

Requirements:
- Return only raw error messages.
- Avoid custom wrappers or decorated metadata.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional


def _single_line(s: str) -> str:
    # Ensure messages are stable and don't introduce embedded newlines into logs/UI.
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = " ".join(s.split())

    return s


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
) -> Dict[str, Any]:
    """
    Convert any exception into a raw error payload.

    Contract:
    - returns {"error": "<message>"} so callers can safely do payload.get("error", "").
    """
    del context, path, tool_descriptor, tool_descriptor_text, tool_surface, routing_hint, request
    message = _single_line(str(exc) or exc.__class__.__name__)
    return {"error": message}


def _exception_trace(exc: BaseException) -> str:
    """
    Optional helper: stringify a traceback when you explicitly want it.
    is not supported auto-attach this to user-facing payloads by default.
    """
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {exc}"

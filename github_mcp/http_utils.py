"""HTTP utilities shared across connector integrations."""

from __future__ import annotations

from typing import Any, Dict


def build_response_payload(resp: Any, *, body: Any | None = None) -> Dict[str, Any]:
    """Build a stable response payload.

    This helper intentionally accepts a duck-typed response object so it can be
    reused in multiple integration clients without creating import cycles.
    """

    payload: Dict[str, Any] = {
        "status_code": getattr(resp, "status_code", None),
        "headers": dict(getattr(resp, "headers", {}) or {}),
    }
    if body is not None:
        payload["json"] = body
    else:
        payload["text"] = getattr(resp, "text", "")
    return payload


__all__ = ["build_response_payload"]

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.mcp_server.context import get_request_context
from github_mcp.session_anchor import get_server_anchor, normalize_anchor


def _effective_session_id(request: Request) -> Optional[str]:
    # Prefer query param to align with existing /messages?session_id=... behavior.
    sid = request.query_params.get("session_id")
    if sid:
        s = str(sid).strip()
        if s:
            return s

    # Fall back to contextvar populated from headers.
    ctx = get_request_context()
    sid2 = ctx.get("session_id")
    if sid2:
        s2 = str(sid2).strip()
        if s2:
            return s2

    chatgpt = ctx.get("chatgpt")
    if isinstance(chatgpt, dict):
        cg = chatgpt.get("session_id")
        if cg:
            s3 = str(cg).strip()
            if s3:
                return s3

    return None


def build_session_anchor_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        refresh = str(request.query_params.get("refresh") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        anchor, payload = get_server_anchor(refresh=refresh)
        return JSONResponse(
            {
                "anchor": anchor,
                "payload": payload,
                "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": _effective_session_id(request),
            }
        )

    return _endpoint


def build_session_ping_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        anchor, _payload = get_server_anchor()
        return JSONResponse(
            {
                "ok": True,
                "anchor": anchor,
                "server_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": _effective_session_id(request),
                "request": get_request_context(),
            }
        )

    return _endpoint


def build_session_assert_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        expected = normalize_anchor(
            request.query_params.get("anchor") or request.headers.get("x-session-anchor")
        )
        current, payload = get_server_anchor()
        if not expected:
            return JSONResponse(
                {
                    "ok": False,
                    "status": "missing_anchor",
                    "current": current,
                    "session_id": _effective_session_id(request),
                },
                status_code=400,
            )
        if expected != current:
            return JSONResponse(
                {
                    "ok": False,
                    "status": "anchor_mismatch",
                    "expected": expected,
                    "current": current,
                    "payload": payload,
                    "session_id": _effective_session_id(request),
                },
                status_code=409,
            )
        return JSONResponse(
            {
                "ok": True,
                "status": "anchor_match",
                "current": current,
                "session_id": _effective_session_id(request),
            }
        )

    return _endpoint


def register_session_routes(app: Any) -> None:
    """Register session / drift diagnostics routes."""

    app.add_route("/session/anchor", build_session_anchor_endpoint(), methods=["GET"])
    app.add_route("/session/ping", build_session_ping_endpoint(), methods=["GET"])
    app.add_route("/session/assert", build_session_assert_endpoint(), methods=["GET"])


__all__ = ["register_session_routes"]

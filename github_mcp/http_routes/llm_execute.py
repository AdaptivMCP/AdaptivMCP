from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.http_routes.tool_registry import _execute_tool
from github_mcp.llm_tool_calls import ParsedToolCall, extract_tool_calls_from_text


def _serialize_call(call: ParsedToolCall) -> dict[str, Any]:
    return {
        "tool_name": call.tool_name,
        "args": call.args,
        "channel": call.channel,
        "start": call.start,
        "end": call.end,
    }


def build_llm_execute_endpoint():
    async def _endpoint(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        analysis = payload.get("analysis") or payload.get("analysis_text")
        commentary = payload.get("commentary") or payload.get("commentary_text")
        text = payload.get("text") or payload.get("content")

        # Optional "messages" format: [{"role":"assistant","channel":"analysis","content":"..."}, ...]
        messages = payload.get("messages")
        texts: list[tuple[str, str | None]] = []
        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                channel = msg.get("channel") or msg.get("role") or "message"
                content = msg.get("content")
                if isinstance(content, str):
                    texts.append((str(channel), content))

        if not texts:
            texts = [("analysis", analysis), ("commentary", commentary), ("text", text)]

        max_calls = payload.get("max_calls", 20)
        try:
            max_calls = int(max_calls)
        except Exception:
            max_calls = 20

        calls = extract_tool_calls_from_text(texts, max_calls=max_calls)

        dry_run = bool(payload.get("dry_run")) or request.query_params.get("dry_run") in {"1", "true", "yes"}
        max_attempts = payload.get("max_attempts")
        if max_attempts is not None:
            try:
                max_attempts = int(max_attempts)
            except Exception:
                max_attempts = None

        response: dict[str, Any] = {
            "calls": [_serialize_call(c) for c in calls],
        }

        if dry_run or not calls:
            response["executed"] = False
            return JSONResponse(response)

        results: list[dict[str, Any]] = []
        for call in calls:
            result, status_code, headers = await _execute_tool(
                call.tool_name,
                call.args,
                max_attempts=max_attempts,
            )
            results.append(
                {
                    "tool_name": call.tool_name,
                    "args": call.args,
                    "channel": call.channel,
                    "status_code": status_code,
                    "headers": headers,
                    "result": result,
                }
            )

        response["executed"] = True
        response["results"] = results
        return JSONResponse(response)

    return _endpoint


def register_llm_execute_routes(app: Any) -> None:
    """Register /llm/execute for clients that can't use structured tool-calling."""

    app.add_route("/llm/execute", build_llm_execute_endpoint(), methods=["POST"])


__all__ = ["register_llm_execute_routes"]

"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so clients can see how to interact with the server.
"""

import base64
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs

import anyio
import httpx  # noqa: F401
from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.staticfiles import StaticFiles

import github_mcp.server as server  # noqa: F401
import github_mcp.tools_main as tools_main  # noqa: F401
import github_mcp.tools_workspace as tools_workspace  # noqa: F401
from github_mcp import http_clients as _http_clients  # noqa: F401
from github_mcp.config import (
    BASE_LOGGER,  # noqa: F401
    FETCH_FILES_CONCURRENCY,
    FILE_CACHE_MAX_BYTES,  # noqa: F401
    FILE_CACHE_MAX_ENTRIES,  # noqa: F401
    GITHUB_API_BASE,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    HUMAN_LOGS,
    LOG_HTTP_BODIES,
    LOG_HTTP_MAX_BODY_BYTES,
    LOG_HTTP_REQUESTS,
    LOG_RENDER_HTTP,  # noqa: F401
    LOG_RENDER_HTTP_BODIES,  # noqa: F401
    MAX_CONCURRENCY,
    WORKSPACE_BASE_DIR,  # noqa: F401
    shorten_token,
)
from github_mcp.exceptions import (
    GitHubAPIError,  # noqa: F401
    GitHubAuthError,
    GitHubRateLimitError,  # noqa: F401
    WriteApprovalRequiredError,  # noqa: F401
    WriteNotAuthorizedError,  # noqa: F401
)
from github_mcp.file_cache import (
    clear_cache,
)
from github_mcp.github_content import (
    _decode_github_content,
    _load_body_from_content_url,
    _resolve_file_sha,  # noqa: F401
)
from github_mcp.http_clients import (
    _external_client_instance,  # noqa: F401
    _get_concurrency_semaphore,  # noqa: F401
    _get_github_token,  # noqa: F401
    _github_client_instance,  # noqa: F401
)
from github_mcp.http_routes.healthz import register_healthz_route
from github_mcp.http_routes.llm_execute import register_llm_execute_routes
from github_mcp.http_routes.render import register_render_routes
from github_mcp.http_routes.session import register_session_routes
from github_mcp.http_routes.tool_registry import (
    _response_headers_for_error,
    _status_code_for_error,
    register_tool_registry_routes,
)
from github_mcp.http_routes.ui import register_ui_routes
from github_mcp.mcp_server.context import (
    REQUEST_CHATGPT_METADATA,
    REQUEST_ID,
    REQUEST_IDEMPOTENCY_KEY,
    REQUEST_MESSAGE_ID,
    REQUEST_PATH,
    REQUEST_RECEIVED_AT,
    REQUEST_SESSION_ID,
    _extract_chatgpt_metadata,
)
from github_mcp.server import (
    _REGISTERED_MCP_TOOLS,  # noqa: F401
    COMPACT_METADATA_DEFAULT,
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _find_registered_tool,
    _github_request,
    _normalize_input_schema,
    _structured_tool_error,  # noqa: F401
    mcp_tool,
    register_extra_tools_if_available,
)
from github_mcp.session_anchor import get_server_anchor
from github_mcp.utils import (
    _effective_ref_for_repo,  # noqa: F401
    _with_numbered_lines,
)
from github_mcp.workspace import (
    _clone_repo,  # noqa: F401
    _prepare_temp_virtualenv,  # noqa: F401
    _run_shell,  # noqa: F401
    _workspace_path,  # noqa: F401
)


class _CacheControlMiddleware:
    """ASGI middleware to control Cache-Control headers safely for streaming.

    Avoid BaseHTTPMiddleware here because it can interfere with streaming
    responses (SSE).

    - is not supported cache dynamic streaming endpoints: /sse and /messages
    - Optionally cache static assets: /static/*
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "") or ""
        started = False
        completed = False

        async def send_wrapper(message):
            nonlocal started, completed
            if completed:
                return
            if message.get("type") == "http.response.start":
                if started:
                    return
                started = True
                headers = list(message.get("headers", []))

                # Normalize: remove any existing Cache-Control header if we're overriding.
                def _has_cache_control(hdrs):
                    return any(k.lower() == b"cache-control" for k, _ in hdrs)

                if path.startswith("/static/"):
                    # Honor any explicit Cache-Control set upstream; otherwise make static assets cacheable.
                    if not _has_cache_control(headers):
                        headers.append(
                            (b"cache-control", b"public, max-age=31536000, immutable")
                        )
                else:
                    # Default to no-store for everything else so edge caching (or proxies) never cache dynamic endpoints.
                    headers = [
                        (k, v) for (k, v) in headers if k.lower() != b"cache-control"
                    ]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            elif message.get("type") == "http.response.body":
                if not message.get("more_body", False):
                    completed = True
            await send(message)

        return await self.app(scope, receive, send_wrapper)


class _RequestContextMiddleware:
    """ASGI middleware that extracts stable identifiers for dedupe and logging.

    For POST /messages, we capture:
    - `session_id` from the query string
    - MCP JSON-RPC `id` from the request body

    These values are stored in contextvars and consumed by the tool decorator
    to suppress duplicate tool invocations caused by upstream retries.

    We avoid BaseHTTPMiddleware to preserve streaming semantics.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "") or ""

        # Reset context for this request.
        REQUEST_PATH.set(path)
        REQUEST_RECEIVED_AT.set(time.time())
        REQUEST_SESSION_ID.set(None)
        REQUEST_MESSAGE_ID.set(None)
        REQUEST_ID.set(None)
        REQUEST_IDEMPOTENCY_KEY.set(None)
        REQUEST_CHATGPT_METADATA.set(None)

        # Correlation id: honor upstream X-Request-Id if provided, else generate.
        request_id: str | None = None
        idempotency_key: str | None = None
        try:
            for k, v in scope.get("headers") or []:
                if (k or b"").lower() == b"x-request-id":
                    decoded = (v or b"").decode("utf-8", errors="ignore").strip()
                    if decoded:
                        request_id = decoded
                        break
            for k, v in scope.get("headers") or []:
                lk = (k or b"").lower()
                if lk in {b"idempotency-key", b"x-idempotency-key", b"x-dedupe-key"}:
                    decoded = (v or b"").decode("utf-8", errors="ignore").strip()
                    if decoded:
                        idempotency_key = decoded
                        break
        except Exception:
            request_id = None

        if not request_id:
            request_id = uuid.uuid4().hex
        REQUEST_ID.set(request_id)
        if idempotency_key:
            REQUEST_IDEMPOTENCY_KEY.set(idempotency_key)

        try:
            metadata = _extract_chatgpt_metadata(list(scope.get("headers") or []))
            if metadata:
                REQUEST_CHATGPT_METADATA.set(metadata)
        except Exception:
            pass

        started = False

        async def send_wrapper(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                if started:
                    return
                started = True
                headers = list(message.get("headers", []))
                if not any((hk or b"").lower() == b"x-request-id" for hk, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("utf-8")))

                # Expose a stable "server anchor" so clients can detect redeploys
                # and avoid "drift" when reconnecting.
                try:
                    anchor, _payload = get_server_anchor()
                    if not any(
                        (hk or b"").lower() == b"x-server-anchor" for hk, _ in headers
                    ):
                        headers.append((b"x-server-anchor", anchor.encode("utf-8")))
                except Exception:
                    pass
                message["headers"] = headers
            await send(message)

        # Parse query string for session_id.
        try:
            raw_qs = (scope.get("query_string") or b"").decode("utf-8", errors="ignore")
            qs = parse_qs(raw_qs)
            session_id = (qs.get("session_id") or [None])[0]
            if session_id:
                REQUEST_SESSION_ID.set(str(session_id))
            if not REQUEST_IDEMPOTENCY_KEY.get():
                qs_idempotency = (
                    qs.get("idempotency_key") or qs.get("dedupe_key") or [None]
                )[0]
                if qs_idempotency:
                    REQUEST_IDEMPOTENCY_KEY.set(str(qs_idempotency))
        except Exception:
            pass

        # HTTP access logging (provider logs). We log at response.start and capture
        # status + correlation fields. Bodies are opt-in and only captured for
        # POST /messages.
        access_started_at = time.perf_counter()
        access_logged = False
        captured_body: bytes | None = None
        captured_body_truncated = False

        # Optional response capture (bounded).
        response_status: int | None = None
        response_headers: list[tuple[bytes, bytes]] | None = None
        response_body_chunks: list[bytes] = []
        response_body_total = 0
        response_body_truncated = False

        def _compact_http_payload(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value
                for key, value in payload.items()
                if value not in (None, "", [], {})
            }

        async def send_access_wrapper(message):
            nonlocal access_logged
            nonlocal response_status, response_headers
            nonlocal response_body_total, response_body_truncated
            nonlocal captured_body_truncated
            if not LOG_HTTP_REQUESTS:
                return await send_wrapper(message)
            msg_type = message.get("type")

            if msg_type == "http.response.start":
                response_status = message.get("status")
                response_headers = list(message.get("headers") or [])

                # When body logging is enabled for this request, delay the log
                # until we see the final body chunk so we can include the
                # response payload.
                if LOG_HTTP_BODIES and (
                    captured_body is not None or scope.get("method") == "POST"
                ):
                    return await send_wrapper(message)

                if not access_logged:
                    access_logged = True
                    duration_ms = (time.perf_counter() - access_started_at) * 1000
                    payload = _compact_http_payload(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "session_id": REQUEST_SESSION_ID.get(),
                            "message_id": REQUEST_MESSAGE_ID.get(),
                            "method": scope.get("method"),
                            "path": path,
                            "status_code": response_status,
                            "duration_ms": duration_ms,
                        }
                    )
                    if HUMAN_LOGS:
                        rid = shorten_token(request_id)
                        sid = shorten_token(REQUEST_SESSION_ID.get())
                        mid = shorten_token(REQUEST_MESSAGE_ID.get())
                        LOGGER.info(
                            (
                                "http_request "
                                f"method={scope.get('method')} path={path} status={response_status} "
                                f"duration_ms={duration_ms:.2f} request_id={rid} session_id={sid} message_id={mid}"
                            ),
                            extra=payload,
                        )
                    else:
                        LOGGER.info(
                            f"http_request method={scope.get('method')} path={path} status={response_status}",
                            extra=payload,
                        )
                return await send_wrapper(message)

            if (
                msg_type == "http.response.body"
                and LOG_HTTP_BODIES
                and (captured_body is not None or scope.get("method") == "POST")
            ):
                body_chunk = message.get("body", b"") or b""
                if body_chunk and not response_body_truncated:
                    remaining = max(
                        0, int(LOG_HTTP_MAX_BODY_BYTES) - response_body_total
                    )
                    if remaining > 0:
                        response_body_chunks.append(body_chunk[:remaining])
                        response_body_total += min(len(body_chunk), remaining)
                    if len(body_chunk) > remaining:
                        response_body_truncated = True

                if not message.get("more_body") and not access_logged:
                    access_logged = True
                    duration_ms = (time.perf_counter() - access_started_at) * 1000
                    payload = _compact_http_payload(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "session_id": REQUEST_SESSION_ID.get(),
                            "message_id": REQUEST_MESSAGE_ID.get(),
                            "method": scope.get("method"),
                            "path": path,
                            "status_code": response_status,
                            "duration_ms": duration_ms,
                        }
                    )

                    if captured_body is not None:
                        try:
                            payload["request_body"] = captured_body.decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            payload["request_body"] = repr(captured_body)
                        if captured_body_truncated:
                            payload["request_body_truncated"] = True

                    resp_bytes = b"".join(response_body_chunks)
                    if resp_bytes:
                        try:
                            payload["response_body"] = resp_bytes.decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            payload["response_body"] = repr(resp_bytes)
                        if response_body_truncated:
                            payload["response_body_truncated"] = True

                    if HUMAN_LOGS:
                        rid = shorten_token(request_id)
                        sid = shorten_token(REQUEST_SESSION_ID.get())
                        mid = shorten_token(REQUEST_MESSAGE_ID.get())
                        LOGGER.info(
                            (
                                "http_request "
                                f"method={scope.get('method')} path={path} status={response_status} "
                                f"duration_ms={duration_ms:.2f} request_id={rid} session_id={sid} message_id={mid}"
                            ),
                            extra=payload,
                        )
                    else:
                        LOGGER.info(
                            f"http_request method={scope.get('method')} path={path} status={response_status}",
                            extra=payload,
                        )

                return await send_wrapper(message)
            return await send_wrapper(message)

        def _extract_idempotency_from_payload(payload: Any) -> str | None:
            if not isinstance(payload, dict):
                return None
            for key in ("idempotency_key", "dedupe_key"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for nested_key in ("params", "args", "_meta"):
                nested = payload.get(nested_key)
                if isinstance(nested, dict):
                    for key in ("idempotency_key", "dedupe_key"):
                        value = nested.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
            return None

        def _auto_idempotency_for_tool(path: str, payload: Any) -> str:
            try:
                canonical = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
            except Exception:
                canonical = repr(payload)
            digest = hashlib.sha256(
                f"{path}|{canonical}".encode("utf-8", errors="ignore")
            ).hexdigest()
            return f"auto:{digest[:24]}"

        should_parse_body = scope.get("method") == "POST" and (
            path.endswith("/messages") or path.startswith("/tools/")
        )

        if should_parse_body:
            body_chunks: list[bytes] = []
            total = 0
            more_body = True

            async def _drain_body():
                nonlocal more_body, total
                while more_body:
                    msg = await receive()
                    msg_type = msg.get("type")
                    if msg_type != "http.request":
                        # Avoid infinite loops if the client disconnects or sends
                        # unexpected messages before completing the body.
                        more_body = False
                        break
                    chunk = msg.get("body", b"") or b""
                    if chunk:
                        body_chunks.append(chunk)
                        total += len(chunk)
                    more_body = bool(msg.get("more_body"))

            # Drain once, then replay to downstream app.
            await _drain_body()
            body = b"".join(body_chunks)
            if LOG_HTTP_BODIES:
                limit = max(0, int(LOG_HTTP_MAX_BODY_BYTES))
                if limit and len(body) > limit:
                    captured_body = body[:limit]
                    captured_body_truncated = True
                else:
                    captured_body = body
            else:
                captured_body = None
            try:
                if body:
                    payload = json.loads(body.decode("utf-8", errors="replace"))
                    msg_id = payload.get("id")
                    if msg_id is not None:
                        REQUEST_MESSAGE_ID.set(str(msg_id))
                    if not REQUEST_IDEMPOTENCY_KEY.get():
                        extracted = _extract_idempotency_from_payload(payload)
                        if extracted:
                            REQUEST_IDEMPOTENCY_KEY.set(extracted)
                        elif path.startswith("/tools/"):
                            REQUEST_IDEMPOTENCY_KEY.set(
                                _auto_idempotency_for_tool(path, payload)
                            )
            except Exception:
                pass

            # Replay the drained body to downstream consumers.
            replayed = False

            async def receive_replay():
                nonlocal replayed
                if replayed:
                    return {"type": "http.request", "body": b"", "more_body": False}
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}

            try:
                return await self.app(scope, receive_replay, send_access_wrapper)
            except Exception as exc:
                if LOG_HTTP_REQUESTS:
                    duration_ms = (time.perf_counter() - access_started_at) * 1000
                    payload = _compact_http_payload(
                        {
                            "event": "http_exception",
                            "request_id": request_id,
                            "session_id": REQUEST_SESSION_ID.get(),
                            "message_id": REQUEST_MESSAGE_ID.get(),
                            "method": scope.get("method"),
                            "path": path,
                            "duration_ms": duration_ms,
                            "exception_type": type(exc).__name__,
                        }
                    )
                    LOGGER.info(
                        (
                            "http_exception "
                            f"method={scope.get('method')} path={path} request_id={shorten_token(request_id)} "
                            f"duration_ms={duration_ms:.2f}"
                        ),
                        extra={"severity": "error", **payload},
                        exc_info=True,
                    )
                raise

        try:
            return await self.app(scope, receive, send_access_wrapper)
        except Exception as exc:
            if LOG_HTTP_REQUESTS:
                duration_ms = (time.perf_counter() - access_started_at) * 1000
                payload = _compact_http_payload(
                    {
                        "event": "http_exception",
                        "request_id": request_id,
                        "session_id": REQUEST_SESSION_ID.get(),
                        "message_id": REQUEST_MESSAGE_ID.get(),
                        "method": scope.get("method"),
                        "path": path,
                        "duration_ms": duration_ms,
                        "exception_type": type(exc).__name__,
                    }
                )
                LOGGER.info(
                    (
                        "http_exception "
                        f"method={scope.get('method')} path={path} request_id={shorten_token(request_id)} "
                        f"duration_ms={duration_ms:.2f}"
                    ),
                    extra={"severity": "error", **payload},
                    exc_info=True,
                )
            raise


class _SuppressClientDisconnectMiddleware:
    """Suppress disconnect errors from streaming responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            return await self.app(scope, receive, send)
        except (
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            anyio.EndOfStream,
        ):
            return
        except Exception as exc:
            # Python 3.12+ includes ExceptionGroup / BaseExceptionGroup.
            # Some runtimes (or dependency sets) may not expose these names at
            # import time. To remain compatible, detect "exception group" shape
            # via duck-typing rather than referencing ExceptionGroup directly.
            excs = getattr(exc, "exceptions", None)
            if exc.__class__.__name__ in {
                "ExceptionGroup",
                "BaseExceptionGroup",
            } and isinstance(excs, tuple):
                if all(
                    isinstance(
                        err,
                        (
                            anyio.ClosedResourceError,
                            anyio.BrokenResourceError,
                            anyio.EndOfStream,
                        ),
                    )
                    for err in excs
                ):
                    return
            raise


# Re-exported symbols used by helper modules and tests that import `main`.
__all__ = [
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "WriteApprovalRequiredError",
    "WriteNotAuthorizedError",
    "GITHUB_API_BASE",
    "HTTPX_TIMEOUT",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "MAX_CONCURRENCY",
    "FETCH_FILES_CONCURRENCY",
    "CONTROLLER_REPO",
    "CONTROLLER_DEFAULT_BRANCH",
    "_github_request",
]
# Exposed for tests that monkeypatch the external HTTP client used for sandbox: URLs.
_http_client_external: httpx.AsyncClient | None = None

LOGGER = BASE_LOGGER.getChild("main")

# Keep selected symbols in main for tests/backwards-compat and for impl modules.
_EXPORT_COMPAT = (
    COMPACT_METADATA_DEFAULT,
    _find_registered_tool,
    _normalize_input_schema,
)


async def _perform_github_commit_and_refresh_workspace(
    *,
    full_name: str,
    path: str,
    message: str,
    branch: str,
    body_bytes: bytes,
    sha: str | None,
) -> dict[str, Any]:
    """Perform a Contents API commit and then refresh the repo mirror."""
    from github_mcp.main_tools.workspace_sync import (
        _perform_github_commit_and_refresh_workspace as _impl,
    )

    return await _impl(
        full_name=full_name,
        path=path,
        message=message,
        branch=branch,
        body_bytes=body_bytes,
        sha=sha,
    )


async def _perform_github_commit(
    full_name: str,
    *,
    branch: str,
    path: str,
    message: str,
    body_bytes: bytes,
    sha: str | None,
    committer: dict[str, str] | None = None,
    author: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compat wrapper for github_mcp.github_content._perform_github_commit."""
    from github_mcp.github_content import _perform_github_commit as _impl

    return await _impl(
        full_name,
        branch=branch,
        path=path,
        message=message,
        body_bytes=body_bytes,
        sha=sha,
        committer=committer,
        author=author,
    )


def __getattr__(name: str):
    if name == "WRITE_ALLOWED":
        return server.WRITE_ALLOWED
    raise AttributeError(name)


# Recalculate write-allowed state on first import to honor updated environment variables when
# ``main`` is reloaded in tests, while keeping the env var as the single authoritative value.
if not getattr(server, "_WRITE_ALLOWED_INITIALIZED", False):
    from github_mcp.mcp_server.context import (
        WRITE_ALLOWED as _CONTEXT_WRITE_ALLOWED,
    )
    from github_mcp.mcp_server.context import (
        get_write_allowed as _get_write_allowed,
    )

    # Ensure the exported server attribute always references the context-backed flag object (not a bool).
    server.WRITE_ALLOWED = _CONTEXT_WRITE_ALLOWED
    _get_write_allowed(refresh_after_seconds=0.0)
    server._WRITE_ALLOWED_INITIALIZED = True

register_extra_tools_if_available()

# Expose an ASGI app for hosting via uvicorn/Render. The FastMCP server lazily
# constructs a Starlette application through ``http_app`` (newer releases), but
# older versions used ``sse_app``/``app`` helpers. Build the app once at import
# time so ``uvicorn main:app`` works across versions.
#
# Force the SSE transport so the controller serves ``/sse`` again. FastMCP 2.14
# defaults to the streamable HTTP transport, which removed the SSE route and
# caused the public endpoint to return ``404 Not Found``. Using the SSE transport
# keeps the documented ``/sse`` path working for existing clients.
if hasattr(server.mcp, "http_app"):
    try:
        app = server.mcp.http_app(path="/sse", transport="sse")
    except TypeError:
        try:
            app = server.mcp.http_app(transport="sse")
        except TypeError:
            app = server.mcp.http_app()
elif hasattr(server.mcp, "sse_app"):
    try:
        app = server.mcp.sse_app(path="/sse")
    except TypeError:
        app = server.mcp.sse_app()
elif hasattr(server.mcp, "app"):
    app_factory = server.mcp.app
    if callable(app_factory):
        try:
            app = app_factory(path="/sse")
        except TypeError:
            app = app_factory()
    else:
        app = app_factory
else:
    # In minimal/test environments FastMCP may be absent or may not expose an ASGI
    # app factory. Avoid raising at import time so helper functions (e.g.
    # _configure_trusted_hosts) remain testable.
    app = Starlette()


def _configure_trusted_hosts(app_instance) -> None:
    del app_instance
    return


if app is not None:
    _configure_trusted_hosts(app)
if app is not None:
    app.add_middleware(_CacheControlMiddleware)
if app is not None:
    app.add_middleware(_RequestContextMiddleware)
if app is not None:
    app.add_middleware(_SuppressClientDisconnectMiddleware)


async def _handle_value_error(request, exc):
    if str(exc) == "Request validation failed":
        return PlainTextResponse("Request validation failed", status_code=400)
    raise exc


if app is not None:
    app.add_exception_handler(ValueError, _handle_value_error)


async def _handle_unexpected_error(request, exc):
    if isinstance(exc, StarletteHTTPException):
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    structured = _structured_tool_error(
        exc,
        context="http",
        path=str(getattr(getattr(request, "url", None), "path", "") or ""),
    )
    detail = structured.get("error_detail")
    detail_dict = detail if isinstance(detail, dict) else {"category": "internal"}
    status_code = _status_code_for_error(detail_dict)
    headers = _response_headers_for_error(detail_dict)
    LOGGER.info(
        "Unhandled exception",
        extra={"severity": "error", "path": request.url.path},
        exc_info=True,
    )
    return JSONResponse(structured, status_code=status_code, headers=headers)


if app is not None:
    app.add_exception_handler(Exception, _handle_unexpected_error)


try:
    # An absolute path keeps static mounting consistent regardless of CWD.
    # (e.g., running via uvicorn, pytest, or hosted platforms like Render).
    _assets_dir = Path(__file__).resolve().parent / "assets"
    app.mount("/static", StaticFiles(directory=str(_assets_dir)), name="static")
except Exception:
    # Static assets are optional; failures should not prevent server startup.
    pass

register_healthz_route(app)
register_tool_registry_routes(app)
register_ui_routes(app)
register_render_routes(app)
register_session_routes(app)
register_llm_execute_routes(app)


def _reset_file_cache_for_tests() -> None:
    clear_cache()


async def terminal_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Run a shell command in the persistent repo mirror (terminal gateway).

    This is a thin wrapper around github_mcp.tools_workspace.terminal_command.
    """
    return await tools_workspace.terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Legacy shim retained for tests/backwards-compat.

    The MCP tool name `run_command` has been removed from the server tool
    surface. This function remains as a Python-level helper for tests or
    callers importing `main.run_command` directly.

    It forwards to terminal_command.
    """
    # Intentionally delegate to terminal_command so any future behavior
    # changes (logging, env handling, defaults) stay consistent.
    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


async def run_shell(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Legacy shim retained for tests/backwards-compat.

    Some integrations historically called the workspace terminal runner
    `run_shell`. This Python-level helper forwards to terminal_command.
    """

    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


async def terminal_commands(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Legacy shim retained for tests/backwards-compat.

    Some integrations referred to the workspace terminal runner as
    `terminal_commands`. This Python-level helper forwards to terminal_command.
    """

    return await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest -q",
    timeout_seconds: int = 600,
    workdir: str | None = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Forward run_tests calls to the repo mirror helper for test surfaces."""

    return await tools_workspace.run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


async def commit_workspace_files(
    full_name: str,
    files: list[str],
    ref: str = "main",
    message: str = "Commit selected workspace changes",
    push: bool = True,
) -> dict[str, Any]:
    """Forward commit_workspace_files calls to the repo mirror tool.

    Keeping this shim in main preserves the test-oriented API surface
    without duplicating implementation details.
    """
    return await tools_workspace.commit_workspace_files(
        full_name=full_name,
        files=files,
        ref=ref,
        message=message,
        push=push,
    )


# ------------------------------------------------------------------------------
# Read-only tools


# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def get_server_config() -> dict[str, Any]:
    from github_mcp.main_tools.server_config import get_server_config as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def get_repo_defaults(
    full_name: str | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.server_config import get_repo_defaults as _impl

    return await _impl(full_name=full_name)


@mcp_tool(write_action=False)
async def validate_environment() -> dict[str, Any]:
    """Check GitHub-related environment settings and report problems."""
    from github_mcp.main_tools.env import validate_environment as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def list_render_owners(
    cursor: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """List Render owners (workspaces + personal owners)."""

    from github_mcp.main_tools.render import list_render_owners as _impl

    return await _impl(cursor=cursor, limit=limit)


@mcp_tool(write_action=False)
async def list_render_services(
    owner_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List Render services (optionally filtered by owner_id)."""

    from github_mcp.main_tools.render import list_render_services as _impl

    return await _impl(owner_id=owner_id, cursor=cursor, limit=limit)


@mcp_tool(write_action=False)
async def get_render_service(service_id: str) -> dict[str, Any]:
    """Fetch a Render service by id."""

    from github_mcp.main_tools.render import get_render_service as _impl

    return await _impl(service_id=service_id)


@mcp_tool(write_action=False)
async def list_render_deploys(
    service_id: str,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List deploys for a Render service."""

    from github_mcp.main_tools.render import list_render_deploys as _impl

    return await _impl(service_id=service_id, cursor=cursor, limit=limit)


@mcp_tool(write_action=False)
async def get_render_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Fetch a specific deploy for a service."""

    from github_mcp.main_tools.render import get_render_deploy as _impl

    return await _impl(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(write_action=True)
async def create_render_deploy(
    service_id: str,
    clear_cache: bool = False,
    commit_id: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Trigger a new deploy for a Render service."""

    from github_mcp.main_tools.render import create_render_deploy as _impl

    return await _impl(
        service_id=service_id,
        clear_cache=clear_cache,
        commit_id=commit_id,
        image_url=image_url,
    )


@mcp_tool(write_action=True)
async def cancel_render_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Cancel an in-progress Render deploy."""

    from github_mcp.main_tools.render import cancel_render_deploy as _impl

    return await _impl(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(write_action=True)
async def rollback_render_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Roll back a service to the specified deploy."""

    from github_mcp.main_tools.render import rollback_render_deploy as _impl

    return await _impl(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(write_action=True)
async def restart_render_service(service_id: str) -> dict[str, Any]:
    """Restart a Render service."""

    from github_mcp.main_tools.render import restart_render_service as _impl

    return await _impl(service_id=service_id)


@mcp_tool(write_action=True)
async def create_render_service(service_spec: dict[str, Any]) -> dict[str, Any]:
    """Create a new Render service."""

    from github_mcp.main_tools.render import create_render_service as _impl

    return await _impl(service_spec=service_spec)


@mcp_tool(write_action=False)
async def list_render_service_env_vars(service_id: str) -> dict[str, Any]:
    """List environment variables configured for a Render service."""

    from github_mcp.main_tools.render import list_render_service_env_vars as _impl

    return await _impl(service_id=service_id)


@mcp_tool(write_action=True)
async def set_render_service_env_vars(
    service_id: str,
    env_vars: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace environment variables for a Render service."""

    from github_mcp.main_tools.render import set_render_service_env_vars as _impl

    return await _impl(service_id=service_id, env_vars=env_vars)


@mcp_tool(write_action=True)
async def patch_render_service(
    service_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Patch a Render service."""

    from github_mcp.main_tools.render import patch_render_service as _impl

    return await _impl(service_id=service_id, patch=patch)


@mcp_tool(write_action=False)
async def get_render_logs(
    resource_type: str,
    resource_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Fetch logs for a Render resource."""

    from github_mcp.main_tools.render import get_render_logs as _impl

    return await _impl(
        resource_type=resource_type,
        resource_id=resource_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@mcp_tool(write_action=False)
async def list_render_logs(
    owner_id: str,
    resources: list[str],
    start_time: str | None = None,
    end_time: str | None = None,
    direction: str = "backward",
    limit: int = 200,
    instance: str | None = None,
    host: str | None = None,
    level: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    path: str | None = None,
    text: str | None = None,
    log_type: str | None = None,
) -> dict[str, Any]:
    """List logs for one or more Render resources.

    This maps to Render's public /v1/logs API which requires an owner_id and one
    or more resource ids.
    """

    from github_mcp.main_tools.render import list_render_logs as _impl

    return await _impl(
        owner_id=owner_id,
        resources=resources,
        start_time=start_time,
        end_time=end_time,
        direction=direction,
        limit=limit,
        instance=instance,
        host=host,
        level=level,
        method=method,
        status_code=status_code,
        path=path,
        text=text,
        log_type=log_type,
    )


# ------------------------------------------------------------------------------
# Render tool aliases
#
# Some MCP clients (and some prompt templates) expect tool names to
# begin with a provider prefix (for example: render_list_services). We keep the
# canonical tool names (list_render_services, etc.) but also register a stable
# set of render_* aliases so discovery and invocation remain reliable.
# ------------------------------------------------------------------------------


@mcp_tool(
    write_action=False,
    name="render_list_owners",
    ui={"group": "render", "icon": "🟦", "label": "List Owners", "danger": "low"},
)
async def render_list_owners(
    cursor: str | None = None, limit: int = 20
) -> dict[str, Any]:
    return await list_render_owners(cursor=cursor, limit=limit)


@mcp_tool(
    write_action=False,
    name="render_list_services",
    ui={"group": "render", "icon": "🟦", "label": "List Services", "danger": "low"},
)
async def render_list_services(
    owner_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    return await list_render_services(owner_id=owner_id, cursor=cursor, limit=limit)


@mcp_tool(
    write_action=False,
    name="render_get_service",
    ui={"group": "render", "icon": "🟦", "label": "Get Service", "danger": "low"},
)
async def render_get_service(service_id: str) -> dict[str, Any]:
    return await get_render_service(service_id=service_id)


@mcp_tool(
    write_action=False,
    name="render_list_deploys",
    ui={"group": "render", "icon": "🟦", "label": "List Deploys", "danger": "low"},
)
async def render_list_deploys(
    service_id: str,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    return await list_render_deploys(service_id=service_id, cursor=cursor, limit=limit)


@mcp_tool(
    write_action=False,
    name="render_get_deploy",
    ui={"group": "render", "icon": "🟦", "label": "Get Deploy", "danger": "low"},
)
async def render_get_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    return await get_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_create_deploy",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🚀", "label": "Create Deploy", "danger": "high"},
)
async def render_create_deploy(
    service_id: str,
    clear_cache: bool = False,
    commit_id: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    return await create_render_deploy(
        service_id=service_id,
        clear_cache=clear_cache,
        commit_id=commit_id,
        image_url=image_url,
    )


@mcp_tool(
    write_action=True,
    name="render_cancel_deploy",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🛑", "label": "Cancel Deploy", "danger": "high"},
)
async def render_cancel_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    return await cancel_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_rollback_deploy",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "⏪", "label": "Rollback Deploy", "danger": "high"},
)
async def render_rollback_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    return await rollback_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_restart_service",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🔁", "label": "Restart Service", "danger": "high"},
)
async def render_restart_service(service_id: str) -> dict[str, Any]:
    return await restart_render_service(service_id=service_id)


@mcp_tool(
    write_action=True,
    name="render_create_service",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🧱", "label": "Create Service", "danger": "high"},
)
async def render_create_service(service_spec: dict[str, Any]) -> dict[str, Any]:
    return await create_render_service(service_spec=service_spec)


@mcp_tool(
    write_action=False,
    name="render_list_env_vars",
    ui={"group": "render", "icon": "🟦", "label": "List Env Vars", "danger": "low"},
)
async def render_list_env_vars(service_id: str) -> dict[str, Any]:
    return await list_render_service_env_vars(service_id=service_id)


@mcp_tool(
    write_action=True,
    name="render_set_env_vars",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🧪", "label": "Set Env Vars", "danger": "high"},
)
async def render_set_env_vars(
    service_id: str, env_vars: list[dict[str, Any]]
) -> dict[str, Any]:
    return await set_render_service_env_vars(service_id=service_id, env_vars=env_vars)


@mcp_tool(
    write_action=True,
    name="render_patch_service",
    open_world_hint=True,
    destructive_hint=True,
    ui={"group": "render", "icon": "🧩", "label": "Patch Service", "danger": "high"},
)
async def render_patch_service(
    service_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    return await patch_render_service(service_id=service_id, patch=patch)


@mcp_tool(
    write_action=False,
    name="render_get_logs",
    open_world_hint=True,
    ui={"group": "render", "icon": "📜", "label": "Get Logs", "danger": "low"},
)
async def render_get_logs(
    resource_type: str,
    resource_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    return await get_render_logs(
        resource_type=resource_type,
        resource_id=resource_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@mcp_tool(
    write_action=False,
    name="render_list_logs",
    open_world_hint=True,
    ui={"group": "render", "icon": "📜", "label": "List Logs", "danger": "low"},
)
async def render_list_logs(
    owner_id: str,
    resources: list[str],
    start_time: str | None = None,
    end_time: str | None = None,
    direction: str = "backward",
    limit: int = 200,
    instance: str | None = None,
    host: str | None = None,
    level: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    path: str | None = None,
    text: str | None = None,
    log_type: str | None = None,
) -> dict[str, Any]:
    return await list_render_logs(
        owner_id=owner_id,
        resources=resources,
        start_time=start_time,
        end_time=end_time,
        direction=direction,
        limit=limit,
        instance=instance,
        host=host,
        level=level,
        method=method,
        status_code=status_code,
        path=path,
        text=text,
        log_type=log_type,
    )


@mcp_tool(write_action=True)
async def pr_smoke_test(
    full_name: str | None = None,
    base_branch: str | None = None,
    draft: bool = True,
) -> dict[str, Any]:
    from github_mcp.main_tools.diagnostics import pr_smoke_test as _impl

    return await _impl(full_name=full_name, base_branch=base_branch, draft=draft)


@mcp_tool(write_action=False)
async def get_rate_limit() -> dict[str, Any]:
    from github_mcp.main_tools.repositories import get_rate_limit as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def get_user_login() -> dict[str, Any]:
    from github_mcp.main_tools.repositories import get_user_login as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def list_repositories(
    affiliation: str | None = None,
    visibility: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    from github_mcp.main_tools.repositories import list_repositories as _impl

    return await _impl(
        affiliation=affiliation, visibility=visibility, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def list_repositories_by_installation(
    installation_id: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    from github_mcp.main_tools.repositories import (
        list_repositories_by_installation as _impl,
    )

    return await _impl(installation_id=installation_id, per_page=per_page, page=page)


@mcp_tool(write_action=True)
async def create_repository(
    name: str,
    owner: str | None = None,
    owner_type: Literal["auto", "user", "org"] = "auto",
    description: str | None = None,
    homepage: str | None = None,
    visibility: Literal["public", "private", "internal"] | None = None,
    private: bool | None = None,
    auto_init: bool = True,
    gitignore_template: str | None = None,
    license_template: str | None = None,
    is_template: bool = False,
    has_issues: bool = True,
    has_projects: bool | None = None,
    has_wiki: bool = True,
    has_discussions: bool | None = None,
    team_id: int | None = None,
    security_and_analysis: dict[str, Any] | None = None,
    template_full_name: str | None = None,
    include_all_branches: bool = False,
    topics: list[str] | None = None,
    create_payload_overrides: dict[str, Any] | None = None,
    update_payload_overrides: dict[str, Any] | None = None,
    clone_to_workspace: bool = False,
    clone_ref: str | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.repositories import create_repository as _impl

    return await _impl(
        name=name,
        owner=owner,
        owner_type=owner_type,
        description=description,
        homepage=homepage,
        visibility=visibility,
        private=private,
        auto_init=auto_init,
        gitignore_template=gitignore_template,
        license_template=license_template,
        is_template=is_template,
        has_issues=has_issues,
        has_projects=has_projects,
        has_wiki=has_wiki,
        has_discussions=has_discussions,
        team_id=team_id,
        security_and_analysis=security_and_analysis,
        template_full_name=template_full_name,
        include_all_branches=include_all_branches,
        topics=topics,
        create_payload_overrides=create_payload_overrides,
        update_payload_overrides=update_payload_overrides,
        clone_to_workspace=clone_to_workspace,
        clone_ref=clone_ref,
    )


@mcp_tool(write_action=False)
async def list_recent_issues(
    filter: str = "assigned",
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    from github_mcp.main_tools.issues import list_recent_issues as _impl

    return await _impl(filter=filter, state=state, per_page=per_page, page=page)


@mcp_tool(write_action=False)
async def list_repository_issues(
    full_name: str,
    state: str = "open",
    labels: list[str] | None = None,
    assignee: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    from github_mcp.main_tools.issues import list_repository_issues as _impl

    return await _impl(
        full_name=full_name,
        state=state,
        labels=labels,
        assignee=assignee,
        per_page=per_page,
        page=page,
    )


@mcp_tool(write_action=False)
async def list_open_issues_graphql(
    full_name: str,
    state: Literal["open", "closed", "all"] = "open",
    per_page: int = 30,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List issues (excluding PRs) using GraphQL, with cursor-based pagination."""
    from github_mcp.main_tools.graphql_dashboard import (
        list_open_issues_graphql as _impl,
    )

    return await _impl(
        full_name=full_name,
        state=state,
        per_page=per_page,
        cursor=cursor,
    )


@mcp_tool(write_action=False)
async def fetch_issue(full_name: str, issue_number: int) -> dict[str, Any]:
    from github_mcp.main_tools.issues import fetch_issue as _impl

    return await _impl(full_name=full_name, issue_number=issue_number)


@mcp_tool(write_action=False)
async def fetch_issue_comments(
    full_name: str, issue_number: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    from github_mcp.main_tools.issues import fetch_issue_comments as _impl

    return await _impl(
        full_name=full_name, issue_number=issue_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def fetch_pr(full_name: str, pull_number: int) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import fetch_pr as _impl

    return await _impl(full_name=full_name, pull_number=pull_number)


@mcp_tool(write_action=False)
async def get_pr_info(full_name: str, pull_number: int) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import get_pr_info as _impl

    return await _impl(full_name=full_name, pull_number=pull_number)


@mcp_tool(write_action=False)
async def fetch_pr_comments(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import fetch_pr_comments as _impl

    return await _impl(
        full_name=full_name, pull_number=pull_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def list_pr_changed_filenames(
    full_name: str, pull_number: int, per_page: int = 100, page: int = 1
) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import list_pr_changed_filenames as _impl

    return await _impl(
        full_name=full_name, pull_number=pull_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def get_commit_combined_status(full_name: str, ref: str) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import get_commit_combined_status as _impl

    return await _impl(full_name=full_name, ref=ref)


@mcp_tool(write_action=False)
async def get_issue_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    from github_mcp.main_tools.issues import get_issue_comment_reactions as _impl

    return await _impl(
        full_name=full_name, comment_id=comment_id, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def get_pr_reactions(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """Fetch reactions for a GitHub pull request."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/issues/{pull_number}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


@mcp_tool(write_action=False)
async def get_pr_review_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """Fetch reactions for a pull request review comment."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/pulls/comments/{comment_id}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


@mcp_tool(write_action=False)
def list_write_tools() -> dict[str, Any]:
    """Describe write-capable tools exposed by this server.

    This provides a concise summary without requiring a scan of the full module.
    """
    from github_mcp.main_tools.introspection import list_write_tools as _impl

    return _impl()


@mcp_tool(
    write_action=False,
    description="Enumerate write-capable MCP tools with optional schemas.",
)
def list_write_actions(
    include_parameters: bool = False, compact: bool | None = None
) -> dict[str, Any]:
    """Enumerate write-capable MCP tools with optional schemas."""
    from github_mcp.main_tools.introspection import list_write_actions as _impl

    return _impl(include_parameters=include_parameters, compact=compact)


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> dict[str, Any]:
    """Look up repository metadata (topics, default branch, permissions)."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request("GET", f"/repos/{full_name}")


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> dict[str, Any]:
    """Enumerate branches for a repository with GitHub-style pagination."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name}/branches", params=params)


@mcp_tool(write_action=True)
async def move_file(
    full_name: str,
    from_path: str,
    to_path: str,
    branch: str = "main",
    message: str | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.files import move_file as _impl

    return await _impl(
        full_name=full_name,
        from_path=from_path,
        to_path=to_path,
        branch=branch,
        message=message,
    )


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> dict[str, Any]:
    """Fetch a single file from GitHub and decode base64 to UTF-8 text."""

    # Resolve moving refs (like branch names) to an immutable commit SHA so the
    # in-process cache never serves stale content after the branch advances.
    from github_mcp.main_tools.content_cache import _resolve_ref_snapshot

    snapshot = await _resolve_ref_snapshot(full_name, ref)
    requested_ref = snapshot["requested_ref"]
    resolved_ref = snapshot["resolved_ref"]

    decoded = await _decode_github_content(full_name, path, resolved_ref)
    if isinstance(decoded, dict):
        decoded = {
            **decoded,
            "requested_ref": requested_ref,
            "resolved_ref": resolved_ref,
        }

    # Keep the local cache warm for subsequent reads.
    from github_mcp.main_tools.content_cache import _cache_file_result as _cache_impl

    _cache_impl(full_name=full_name, path=path, ref=resolved_ref, decoded=decoded)
    return decoded


@mcp_tool(write_action=False)
async def get_file_excerpt(
    full_name: str,
    path: str,
    ref: str = "main",
    start_byte: int | None = None,
    max_bytes: int = 65536,
    tail_bytes: int | None = None,
    as_text: bool = True,
    max_text_chars: int = 200000,
    numbered_lines: bool = True,
) -> dict[str, Any]:
    from github_mcp.main_tools.large_files import get_file_excerpt as _impl

    return await _impl(
        full_name=full_name,
        path=path,
        ref=ref,
        start_byte=start_byte,
        max_bytes=max_bytes,
        tail_bytes=tail_bytes,
        as_text=as_text,
        max_text_chars=max_text_chars,
        numbered_lines=numbered_lines,
    )


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: list[str],
    ref: str = "main",
) -> dict[str, Any]:
    from github_mcp.main_tools.content_cache import fetch_files as _impl

    return await _impl(full_name=full_name, paths=paths, ref=ref)


@mcp_tool(
    write_action=False,
    description=(
        "Return cached file payloads for a repository/ref without re-fetching "
        "from GitHub. Entries persist for the lifetime of the server process "
        "until evicted by size or entry caps."
    ),
    tags=["github", "cache", "files"],
)
async def get_cached_files(
    full_name: str,
    paths: list[str],
    ref: str = "main",
) -> dict[str, Any]:
    from github_mcp.main_tools.content_cache import get_cached_files as _impl

    return await _impl(full_name=full_name, paths=paths, ref=ref)


@mcp_tool(
    write_action=False,
    description=(
        "Fetch one or more files and persist them in the server-side cache so "
        "callers can reuse them without repeating GitHub reads. "
        "refresh=true bypasses existing cache entries."
    ),
    tags=["github", "cache", "files"],
)
async def cache_files(
    full_name: str,
    paths: list[str],
    ref: str = "main",
    refresh: bool = False,
) -> dict[str, Any]:
    from github_mcp.main_tools.content_cache import cache_files as _impl

    return await _impl(full_name=full_name, paths=paths, ref=ref, refresh=refresh)


@mcp_tool(write_action=False)
async def list_repository_tree(
    full_name: str,
    ref: str = "main",
    path_prefix: str | None = None,
    recursive: bool = True,
    max_entries: int = 1000,
    include_blobs: bool = True,
    include_trees: bool = True,
) -> dict[str, Any]:
    from github_mcp.main_tools.content_cache import list_repository_tree as _impl

    return await _impl(
        full_name=full_name,
        ref=ref,
        path_prefix=path_prefix,
        recursive=recursive,
        max_entries=max_entries,
        include_blobs=include_blobs,
        include_trees=include_trees,
    )


@mcp_tool(write_action=False)
async def graphql_query(
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.querying import graphql_query as _impl

    return await _impl(query=query, variables=variables)


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> dict[str, Any]:
    from github_mcp.main_tools.querying import fetch_url as _impl

    return await _impl(url=url)


@mcp_tool(write_action=False)
async def search(
    query: str,
    search_type: Literal["code", "repositories", "issues", "commits", "users"] = "code",
    per_page: int = 30,
    page: int = 1,
    sort: str | None = None,
    order: Literal["asc", "desc"] | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.querying import search as _impl

    return await _impl(
        query=query,
        search_type=search_type,
        per_page=per_page,
        page=page,
        sort=sort,
        order=order,
    )


@mcp_tool(write_action=False)
async def download_user_content(content_url: str) -> dict[str, Any]:
    """Download user-provided content (sandbox/local/http) with base64 encoding."""

    body_bytes = await _load_body_from_content_url(
        content_url, context="download_user_content"
    )
    text: str | None
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = None

    return {
        "size": len(body_bytes),
        "base64": base64.b64encode(body_bytes).decode("ascii"),
        "text": text,
        "numbered_lines": _with_numbered_lines(text) if text is not None else None,
    }


def _decode_zipped_job_logs(content: bytes) -> str:
    """Decode a zipped GitHub Actions job logs payload into a readable string."""
    from github_mcp.utils import _decode_zipped_job_logs as _impl

    return _impl(content)


# ------------------------------------------------------------------------------
# GitHub Actions tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    branch: str | None = None,
    status: str | None = None,
    event: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List recent GitHub Actions workflow runs with optional filters."""
    from github_mcp.main_tools.workflows import list_workflow_runs as _impl

    return await _impl(
        full_name=full_name,
        branch=branch,
        status=status,
        event=event,
        per_page=per_page,
        page=page,
    )


@mcp_tool(write_action=False)
async def list_workflow_runs_graphql(
    full_name: str,
    per_page: int = 30,
    cursor: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List recent workflow runs using GraphQL with cursor-based pagination."""
    from github_mcp.main_tools.graphql_dashboard import (
        list_workflow_runs_graphql as _impl,
    )

    return await _impl(
        full_name=full_name,
        per_page=per_page,
        cursor=cursor,
        branch=branch,
    )


@mcp_tool(write_action=False)
async def list_recent_failures(
    full_name: str,
    branch: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """List recent failed or cancelled GitHub Actions workflow runs.

    This helper composes ``list_workflow_runs`` and filters to runs whose
    conclusion indicates a non-successful outcome (for example failure,
    cancelled, or timed out). It is intended as a navigation helper for CI
    debugging flows.
    """
    from github_mcp.main_tools.workflows import list_recent_failures as _impl

    return await _impl(full_name=full_name, branch=branch, limit=limit)


@mcp_tool(write_action=False)
async def list_recent_failures_graphql(
    full_name: str,
    branch: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """List recent workflow failures using GraphQL as a fallback."""
    from github_mcp.main_tools.graphql_dashboard import (
        list_recent_failures_graphql as _impl,
    )

    return await _impl(full_name=full_name, branch=branch, limit=limit)


@mcp_tool(
    write_action=False,
    description=(
        "List available MCP tools with a compact description. "
        "Full schemas are available via describe_tool (or list_all_actions with include_parameters=true)."
    ),
)
async def list_tools(
    only_write: bool = False,
    only_read: bool = False,
    name_prefix: str | None = None,
) -> dict[str, Any]:
    """Lightweight tool catalog."""
    from github_mcp.main_tools.introspection import list_tools as _impl

    return await _impl(
        only_write=only_write, only_read=only_read, name_prefix=name_prefix
    )


@mcp_tool(write_action=False)
def list_resources(
    base_path: str | None = None,
    include_parameters: bool = False,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Return a resource catalog derived from registered tools."""
    from github_mcp.main_tools.introspection import list_resources as _impl

    return _impl(
        base_path=base_path, include_parameters=include_parameters, compact=compact
    )


@mcp_tool(write_action=False)
def list_all_actions(
    include_parameters: bool = False, compact: bool | None = None
) -> dict[str, Any]:
    """Enumerate every available MCP tool with optional schemas.

    This helper exposes a structured catalog of all tools so clients can see
    the full command surface without reading this file. It is read-only and
    remains available even when write actions are disabled.

    Args:
    include_parameters: When ``True``, include the serialized input schema
    for each tool to clarify argument names and types.
    compact: When ``True`` (or when ``ADAPTIV_MCP_COMPACT_METADATA_DEFAULT=1`` is
    set), shorten descriptions and omit tag metadata to keep responses
    compact.
    """
    from github_mcp.main_tools.introspection import list_all_actions as _impl

    return _impl(include_parameters=include_parameters, compact=compact)


@mcp_tool(
    write_action=False,
    description=(
        "Return optional schema for one or more tools. "
        "Prefer this over manually scanning list_all_actions in long sessions."
    ),
)
async def describe_tool(
    name: str | None = None,
    names: list[str] | None = None,
    include_parameters: bool = True,
) -> dict[str, Any]:
    """Inspect one or more registered MCP tools by name.

    This is a convenience wrapper around list_all_actions: it lets callers
    inspect specific tools by name without scanning the entire tool catalog.

    Args:
    name: The MCP tool name (for example, "update_files_and_open_pr").
    names: Optional list of tool names to inspect. When provided, up to
    10 tools are returned in a single call. Duplicates are ignored
    while preserving order.
    include_parameters: When True, include the serialized input schema for
    each tool (equivalent to list_all_actions(include_parameters=True)).
    """

    from github_mcp.main_tools.introspection import describe_tool as _impl

    return await _impl(name=name, names=names, include_parameters=include_parameters)


@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> dict[str, Any]:
    """Retrieve a specific workflow run including timing and conclusion."""
    from github_mcp.main_tools.workflows import get_workflow_run as _impl

    return await _impl(full_name=full_name, run_id=run_id)


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List jobs within a workflow run, useful for troubleshooting failures."""
    from github_mcp.main_tools.workflows import list_workflow_run_jobs as _impl

    return await _impl(full_name=full_name, run_id=run_id, per_page=per_page, page=page)


@mcp_tool(write_action=False)
async def get_workflow_run_overview(
    full_name: str,
    run_id: int,
    max_jobs: int = 500,
) -> dict[str, Any]:
    """Summarize a GitHub Actions workflow run for CI triage.

    This helper is read-only and safe to call before any write actions. It
    aggregates run metadata, jobs (with optional pagination up to max_jobs),
    failed jobs, and the longest jobs by duration to provide a single-call
    summary of run status.
    """
    from github_mcp.main_tools.workflows import get_workflow_run_overview as _impl

    return await _impl(full_name=full_name, run_id=run_id, max_jobs=max_jobs)


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job without truncation."""
    from github_mcp.main_tools.workflows import get_job_logs as _impl

    return await _impl(full_name=full_name, job_id=job_id)


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> dict[str, Any]:
    """Poll a workflow run until completion or timeout."""
    from github_mcp.main_tools.workflows import wait_for_workflow_run as _impl

    return await _impl(
        full_name=full_name,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


@mcp_tool(
    write_action=False,
    description=(
        "Return a high-level overview of an issue, including related branches, "
        "pull requests, and checklist items."
    ),
)
async def get_issue_overview(full_name: str, issue_number: int) -> dict[str, Any]:
    """Summarize a GitHub issue for navigation and planning.

    This helper is intentionally read-only.
    It provides context about the issue's current state before changes are made.
    """
    from github_mcp.main_tools.issues import get_issue_overview as _impl

    return await _impl(full_name=full_name, issue_number=issue_number)


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger a workflow dispatch event on the given ref.

    Args:
    full_name: "owner/repo" string.
    workflow: Workflow file name or ID (e.g. "ci.yml" or a numeric ID).
    ref: Git ref (branch, tag, or SHA) to run the workflow on.
    inputs: Optional input payload for workflows that declare inputs.
    """
    from github_mcp.main_tools.workflows import trigger_workflow_dispatch as _impl

    return await _impl(full_name=full_name, workflow=workflow, ref=ref, inputs=inputs)


@mcp_tool(write_action=True)
async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: dict[str, Any] | None = None,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> dict[str, Any]:
    """Trigger a workflow and block until it completes or hits timeout."""
    from github_mcp.main_tools.workflows import trigger_and_wait_for_workflow as _impl

    return await _impl(
        full_name=full_name,
        workflow=workflow,
        ref=ref,
        inputs=inputs,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


# ------------------------------------------------------------------------------
# PR / issue management tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def list_pull_requests(
    full_name: str,
    state: Literal["open", "closed", "all"] = "open",
    head: str | None = None,
    base: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import list_pull_requests as _impl

    return await _impl(
        full_name=full_name,
        state=state,
        head=head,
        base=base,
        per_page=per_page,
        page=page,
    )


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: Literal["merge", "squash", "rebase"] = "squash",
    commit_title: str | None = None,
    commit_message: str | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import merge_pull_request as _impl

    return await _impl(
        full_name=full_name,
        number=number,
        merge_method=merge_method,
        commit_title=commit_title,
        commit_message=commit_message,
    )


@mcp_tool(write_action=True)
async def close_pull_request(full_name: str, number: int) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import close_pull_request as _impl

    return await _impl(full_name=full_name, number=number)


@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> dict[str, Any]:
    from github_mcp.main_tools.pull_requests import comment_on_pull_request as _impl

    return await _impl(full_name=full_name, number=number, body=body)


@mcp_tool(write_action=True)
async def create_issue(
    full_name: str,
    title: str,
    body: str | None = None,
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a GitHub issue in the given repository."""
    from github_mcp.main_tools.issues import create_issue as _impl

    return await _impl(
        full_name=full_name, title=title, body=body, labels=labels, assignees=assignees
    )


@mcp_tool(write_action=True)
async def update_issue(
    full_name: str,
    issue_number: int,
    title: str | None = None,
    body: str | None = None,
    state: Literal["open", "closed"] | None = None,
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> dict[str, Any]:
    """Update fields on an existing GitHub issue."""
    from github_mcp.main_tools.issues import update_issue as _impl

    return await _impl(
        full_name=full_name,
        issue_number=issue_number,
        title=title,
        body=body,
        state=state,
        labels=labels,
        assignees=assignees,
    )


@mcp_tool(write_action=True)
async def comment_on_issue(
    full_name: str,
    issue_number: int,
    body: str,
) -> dict[str, Any]:
    """Post a comment on an issue."""
    from github_mcp.main_tools.issues import comment_on_issue as _impl

    return await _impl(full_name=full_name, issue_number=issue_number, body=body)


@mcp_tool(write_action=False)
async def open_issue_context(full_name: str, issue_number: int) -> dict[str, Any]:
    """Return an issue plus related branches and pull requests."""
    from github_mcp.main_tools.issues import open_issue_context as _impl

    return await _impl(full_name=full_name, issue_number=issue_number)


def _normalize_issue_payload(raw_issue: Any) -> dict[str, Any] | None:
    from github_mcp.main_tools.normalize import normalize_issue_payload as _impl

    return _impl(raw_issue=raw_issue)


def _normalize_pr_payload(raw_pr: Any) -> dict[str, Any] | None:
    from github_mcp.main_tools.normalize import normalize_pr_payload as _impl

    return _impl(raw_pr=raw_pr)


def _normalize_branch_summary(summary: Any) -> dict[str, Any] | None:
    from github_mcp.main_tools.normalize import normalize_branch_summary as _impl

    return _impl(summary=summary)


@mcp_tool(write_action=False)
async def resolve_handle(full_name: str, handle: str) -> dict[str, Any]:
    from github_mcp.main_tools.handles import resolve_handle as _impl

    return await _impl(full_name=full_name, handle=handle)


# ------------------------------------------------------------------------------
# Branch / commit / PR helpers
# ------------------------------------------------------------------------------


@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> dict[str, Any]:
    from github_mcp.main_tools.branches import create_branch as _impl

    return await _impl(full_name=full_name, branch=branch, from_ref=from_ref)


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> dict[str, Any]:
    from github_mcp.main_tools.branches import ensure_branch as _impl

    return await _impl(full_name=full_name, branch=branch, from_ref=from_ref)


@mcp_tool(write_action=False)
async def get_branch_summary(
    full_name: str, branch: str, base: str = "main"
) -> dict[str, Any]:
    from github_mcp.main_tools.branches import get_branch_summary as _impl

    return await _impl(full_name=full_name, branch=branch, base=base)


@mcp_tool(write_action=False)
async def get_latest_branch_status(
    full_name: str, branch: str, base: str = "main"
) -> dict[str, Any]:
    from github_mcp.main_tools.branches import get_latest_branch_status as _impl

    return await _impl(full_name=full_name, branch=branch, base=base)


@mcp_tool(write_action=False)
async def get_repo_dashboard(
    full_name: str, branch: str | None = None
) -> dict[str, Any]:
    """Return a compact, multi-signal dashboard for a repository.

    This helper aggregates several lower-level tools into a single call so
    callers can quickly understand the current state of a repo. It is
    intentionally read-only.

    Args:
    full_name:
    "owner/repo" string.
    branch:
    Optional branch name. When omitted, the repository's default
    branch is used via the same normalization logic as other tools.

    Returns:
    A dict with high-level fields such as:

    - repo: core metadata about the repository (description, visibility,
    default branch, topics, open issue count when available).
    - branch: the effective branch used for lookups.
    - pull_requests: a small window of open pull requests (up to 10).
    - issues: a small window of open issues (up to 10, excluding PRs).
    - workflows: recent GitHub Actions workflow runs on the branch
    (up to 5).
    - top_level_tree: compact listing of top-level files/directories
    on the branch to show the project layout.

    Individual sections degrade gracefully: if one underlying call fails,
    its corresponding "*_error" field is populated instead of raising.
    """
    from github_mcp.main_tools.dashboard import get_repo_dashboard as _impl

    return await _impl(full_name=full_name, branch=branch)


@mcp_tool(write_action=False)
async def get_repo_dashboard_graphql(
    full_name: str, branch: str | None = None
) -> dict[str, Any]:
    """Return a compact dashboard using GraphQL as a fallback."""
    from github_mcp.main_tools.graphql_dashboard import (
        get_repo_dashboard_graphql as _impl,
    )

    return await _impl(full_name=full_name, branch=branch)


async def _build_default_pr_body(
    *,
    full_name: str,
    title: str,
    head: str,
    effective_base: str,
    draft: bool,
) -> str:
    """Compose a rich default PR body when the caller omits one.

    This helper intentionally favors robustness over strictness: if any of the
    underlying GitHub lookups fail, it falls back to partial information instead
    of raising and breaking the overall tool call.
    """
    from github_mcp.main_tools.pull_requests import _build_default_pr_body as _impl

    return await _impl(
        full_name=full_name,
        title=title,
        head=head,
        effective_base=effective_base,
        draft=draft,
    )


@mcp_tool(write_action=True)
async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """Open a pull request from ``head`` into ``base``.

    The base branch is normalized via ``_effective_ref_for_repo`` so that
    controller repos honor the configured default branch even when callers
    supply a simple base name like "main".
    """
    from github_mcp.main_tools.pull_requests import create_pull_request as _impl

    return await _impl(
        full_name=full_name, title=title, head=head, base=base, body=body, draft=draft
    )


@mcp_tool(write_action=True)
async def open_pr_for_existing_branch(
    full_name: str,
    branch: str,
    base: str = "main",
    title: str | None = None,
    body: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """Open a pull request for an existing branch into a base branch.

    This helper is intentionally idempotent: if there is already an open PR for
    the same head/base pair, it will return that existing PR instead of failing
    or creating a duplicate.
    """
    from github_mcp.main_tools.pull_requests import open_pr_for_existing_branch as _impl

    return await _impl(
        full_name=full_name,
        branch=branch,
        base=base,
        title=title,
        body=body,
        draft=draft,
    )


@mcp_tool(write_action=True)
async def update_files_and_open_pr(
    full_name: str,
    title: str,
    files: list[dict[str, Any]],
    base_branch: str = "main",
    new_branch: str | None = None,
    body: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """Commit multiple files, verify each, then open a PR in one call."""
    from github_mcp.main_tools.pull_requests import update_files_and_open_pr as _impl

    return await _impl(
        full_name=full_name,
        title=title,
        files=files,
        base_branch=base_branch,
        new_branch=new_branch,
        body=body,
        draft=draft,
    )


@mcp_tool(write_action=True)
async def create_file(
    full_name: str,
    path: str,
    content: str,
    *,
    branch: str = "main",
    message: str | None = None,
) -> dict[str, Any]:
    from github_mcp.main_tools.files import create_file as _impl

    return await _impl(
        full_name=full_name, path=path, content=content, branch=branch, message=message
    )


@mcp_tool(write_action=True)
async def apply_text_update_and_commit(
    full_name: str,
    path: str,
    updated_content: str,
    *,
    branch: str = "main",
    message: str | None = None,
    return_diff: bool = False,
) -> dict[str, Any]:
    from github_mcp.main_tools.files import apply_text_update_and_commit as _impl

    return await _impl(
        full_name=full_name,
        path=path,
        updated_content=updated_content,
        branch=branch,
        message=message,
        return_diff=return_diff,
    )


@mcp_tool(
    write_action=False,
    description=(
        "Return a compact overview of a pull request, including files and CI status."
    ),
)
async def get_pr_overview(full_name: str, pull_number: int) -> dict[str, Any]:
    # Summarize a pull request for quick review.
    #
    # This helper is read-only and safe to call before any write actions.

    from github_mcp.main_tools.pull_requests import get_pr_overview as _impl

    return await _impl(full_name=full_name, pull_number=pull_number)


@mcp_tool(
    write_action=False,
    description="Return recent pull requests associated with a branch, grouped by state.",
    tags=["github", "read", "navigation", "prs"],
)
async def recent_prs_for_branch(
    full_name: str,
    branch: str,
    include_closed: bool = False,
    per_page_open: int = 20,
    per_page_closed: int = 5,
) -> dict[str, Any]:
    # Return recent pull requests whose head matches the given branch.
    #
    # This is a composite navigation helper built on top of list_pull_requests.
    # It groups results into open and (optionally) closed sets for quick
    # discovery of PRs tied to a feature branch.
    from github_mcp.main_tools.pull_requests import recent_prs_for_branch as _impl

    return await _impl(
        full_name=full_name,
        branch=branch,
        include_closed=include_closed,
        per_page_open=per_page_open,
        per_page_closed=per_page_closed,
    )

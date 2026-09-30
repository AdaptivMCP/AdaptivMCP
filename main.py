"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by hosted connectors. It lists the tools, arguments, and behaviors in a
single place so clients can see how to interact with the server.
"""

import base64
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import parse_qs

import anyio
import httpx  # noqa: F401
from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

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
    LOG_APPEND_EXTRAS,
    LOG_HTTP_BODIES,
    LOG_HTTP_MAX_BODY_BYTES,
    LOG_HTTP_REQUESTS,
    LOG_RENDER_HTTP,  # noqa: F401
    LOG_RENDER_HTTP_BODIES,  # noqa: F401
    MAX_CONCURRENCY,
    WORKSPACE_BASE_DIR,  # noqa: F401
    _sanitize_for_logs,
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
    REQUEST_PRINCIPAL,
    REQUEST_AUTHENTICATED,
    _extract_chatgpt_metadata,
    set_request_capabilities,
)
from github_mcp.mcp_server.transport_auth import (
    authenticate_request,
    auth_configuration_present,
    authentication_error,
    is_public_path,
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


class _TransportAuthMiddleware:
    """Require an explicit bearer credential for MCP-facing HTTP routes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "") or ""
        method = str(scope.get("method", "")).upper()

        # Clear security context before every request so ASGI task reuse cannot
        # carry an authenticated principal or capabilities into another request.
        REQUEST_PRINCIPAL.set(None)
        REQUEST_AUTHENTICATED.set(False)
        set_request_capabilities(())

        if is_public_path(path) or method == "OPTIONS":
            return await self.app(scope, receive, send)

        if not auth_configuration_present():
            response = authentication_error(configuration_error=True)
            await response(scope, receive, send)
            return

        authenticated, principal, capabilities = authenticate_request(
            scope.get("headers") or []
        )
        if not authenticated or principal is None:
            response = authentication_error()
            await response(scope, receive, send)
            return

        REQUEST_PRINCIPAL.set(principal)
        REQUEST_AUTHENTICATED.set(True)
        set_request_capabilities(capabilities)
        return await self.app(scope, receive, send)


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
                    return any((k or b"").lower() == b"cache-control" for k, _ in hdrs)

                if path.startswith("/static/"):
                    # Static assets are generally safe to cache aggressively, but HTML should not be.
                    # If clients (or proxies) hit /static/index.html directly and we mark it immutable,
                    # they'll keep serving a stale UI after deploy.
                    if path.endswith(".html"):
                        headers = [
                            (k, v)
                            for (k, v) in headers
                            if (k or b"").lower() != b"cache-control"
                        ]
                        headers.append((b"cache-control", b"no-store"))
                    else:
                        # Honor any explicit Cache-Control set upstream; otherwise make static assets cacheable.
                        if not _has_cache_control(headers):
                            headers.append(
                                (
                                    b"cache-control",
                                    b"public, max-age=31536000, immutable",
                                )
                            )
                else:
                    # Default to no-store for everything else so edge caching (or proxies) never cache dynamic endpoints.
                    headers = [
                        (k, v)
                        for (k, v) in headers
                        if (k or b"").lower() != b"cache-control"
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
        for k, v in scope.get("headers") or []:
            try:
                if (k or b"").lower() != b"x-request-id":
                    continue
                decoded = (v or b"").decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if decoded:
                request_id = decoded
                break
        for k, v in scope.get("headers") or []:
            try:
                lk = (k or b"").lower()
            except Exception:
                continue
            if lk not in {b"idempotency-key", b"x-idempotency-key", b"x-dedupe-key"}:
                continue
            try:
                decoded = (v or b"").decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if decoded:
                idempotency_key = decoded
                break

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

        def _build_http_payload(event: str, **extras: Any) -> dict[str, Any]:
            return _compact_http_payload(
                {
                    "event": event,
                    "request_id": request_id,
                    "session_id": REQUEST_SESSION_ID.get(),
                    "message_id": REQUEST_MESSAGE_ID.get(),
                    "method": scope.get("method"),
                    "path": path,
                    **extras,
                }
            )

        def _emit_http_request(payload: dict[str, Any]) -> None:
            payload = _sanitize_for_logs(payload)  # type: ignore[assignment]
            duration_ms = payload.get("duration_ms", 0)
            status_code = payload.get("status_code")
            # When we know the formatter will append a structured extras block
            # (LOG_APPEND_EXTRAS + event=http_request), keep the message minimal
            # to avoid duplicating the same fields both inline and in JSON.
            if LOG_APPEND_EXTRAS:
                LOGGER.info("http_request", extra=payload)
                return
            if HUMAN_LOGS:
                rid = shorten_token(request_id)
                sid = shorten_token(REQUEST_SESSION_ID.get())
                mid = shorten_token(REQUEST_MESSAGE_ID.get())
                LOGGER.info(
                    (
                        "http_request "
                        f"method={scope.get('method')} path={path} status={status_code} "
                        f"duration_ms={duration_ms:.2f} request_id={rid} session_id={sid} message_id={mid}"
                    ),
                    extra=payload,
                )
            else:
                LOGGER.info(
                    f"http_request method={scope.get('method')} path={path} status={status_code}",
                    extra=payload,
                )

        def _emit_http_exception(payload: dict[str, Any], exc: Exception) -> None:
            payload = _sanitize_for_logs(payload)  # type: ignore[assignment]
            duration_ms = payload.get("duration_ms", 0)
            # Same strategy as http_request: when extras are appended, avoid
            # embedding redundant key=value pairs in the message.
            if LOG_APPEND_EXTRAS:
                LOGGER.info(
                    "http_exception",
                    extra={"severity": "error", **payload},
                    exc_info=exc,
                )
                return
            LOGGER.info(
                (
                    "http_exception "
                    f"method={scope.get('method')} path={path} request_id={shorten_token(request_id)} "
                    f"duration_ms={duration_ms:.2f}"
                ),
                extra={"severity": "error", **payload},
                exc_info=exc,
            )

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
                    payload = _build_http_payload(
                        "http_request",
                        status_code=response_status,
                        duration_ms=duration_ms,
                    )
                    _emit_http_request(payload)
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
                    payload = _build_http_payload(
                        "http_request",
                        status_code=response_status,
                        duration_ms=duration_ms,
                    )

                    if captured_body is not None:
                        try:
                            decoded = captured_body.decode("utf-8", errors="replace")
                            try:
                                payload["request_json"] = _sanitize_for_logs(
                                    json.loads(decoded)
                                )
                            except Exception:
                                # Keep binary/garbage bodies compact.
                                if "\x00" in decoded or "\ufffd" in decoded:
                                    payload["request_body"] = (
                                        f"<bytes len={len(captured_body)}>"
                                    )
                                else:
                                    payload["request_body"] = _sanitize_for_logs(
                                        decoded
                                    )
                        except Exception:
                            # As a last resort, don't dump repr(...) into logs.
                            try:
                                payload["request_body"] = (
                                    f"<bytes len={len(captured_body)}>"
                                )
                            except Exception:
                                payload["request_body"] = "<bytes>"
                        if captured_body_truncated:
                            payload["request_body_truncated"] = True

                    resp_bytes = b"".join(response_body_chunks)
                    if resp_bytes:
                        try:
                            decoded = resp_bytes.decode("utf-8", errors="replace")
                            try:
                                payload["response_json"] = _sanitize_for_logs(
                                    json.loads(decoded)
                                )
                            except Exception:
                                if "\x00" in decoded or "\ufffd" in decoded:
                                    payload["response_body"] = (
                                        f"<bytes len={len(resp_bytes)}>"
                                    )
                                else:
                                    payload["response_body"] = _sanitize_for_logs(
                                        decoded
                                    )
                        except Exception:
                            try:
                                payload["response_body"] = (
                                    f"<bytes len={len(resp_bytes)}>"
                                )
                            except Exception:
                                payload["response_body"] = "<bytes>"
                        if response_body_truncated:
                            payload["response_body_truncated"] = True

                    _emit_http_request(payload)

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
                    payload = _build_http_payload(
                        "http_exception",
                        duration_ms=duration_ms,
                        exception_type=type(exc).__name__,
                    )
                    _emit_http_exception(payload, exc)
                raise

        try:
            return await self.app(scope, receive, send_access_wrapper)
        except Exception as exc:
            if LOG_HTTP_REQUESTS:
                duration_ms = (time.perf_counter() - access_started_at) * 1000
                payload = _build_http_payload(
                    "http_exception",
                    duration_ms=duration_ms,
                    exception_type=type(exc).__name__,
                )
                _emit_http_exception(payload, exc)
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
# Exposed for tests that monkeypatch the external HTTP client used for URL fetches.
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
    """Expose dynamic module attributes for backward compatibility.

    The server's WRITE_ALLOWED flag is defined in the FastMCP context layer and
    can change based on environment variables. This getter forwards access so
    callers importing ``main.WRITE_ALLOWED`` always observe the live value.
    """
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


def _register_mcp_fallback_route(app_instance: Any) -> None:
    """Ensure /mcp exists even if streamable transport isn't available.

    Some deployments pin MCP SDK versions that do not expose the Streamable HTTP
    transport. Connector flows may still probe `/mcp` with GET/OPTIONS, so we
    provide a non-404 fallback that points to `/sse` + `/messages`.
    """

    if app_instance is None or not callable(getattr(app_instance, "add_route", None)):
        return

    for route in getattr(app_instance, "routes", []) or []:
        if getattr(route, "path", None) in {"/mcp", "/mcp/"}:
            return

    async def _mcp_options(_request) -> Response:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,HEAD,POST,OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
                "Cache-Control": "no-store",
            },
        )

    async def _mcp_probe(_request) -> Response:
        return JSONResponse(
            {
                "ok": False,
                "endpoint": "/mcp",
                "reason": "streamable-http-unavailable",
                "hint": "Streamable HTTP MCP is not available here. Use /sse + /messages.",
                "alternates": {"sse": "/sse", "messages": "/messages"},
            },
            headers={"Cache-Control": "no-store"},
        )

    async def _mcp_not_supported(_request) -> Response:
        return JSONResponse(
            {
                "ok": False,
                "endpoint": "/mcp",
                "reason": "streamable-http-unavailable",
                "hint": "Configure your client for /sse + /messages.",
            },
            status_code=501,
            headers={"Cache-Control": "no-store"},
        )

    for path in ("/mcp", "/mcp/"):
        app_instance.add_route(path, _mcp_options, methods=["OPTIONS"])
        app_instance.add_route(path, _mcp_probe, methods=["GET", "HEAD"])
        app_instance.add_route(path, _mcp_not_supported, methods=["POST"])


def _try_mount_streamable_http(app_instance: Any) -> None:
    """Mount Streamable HTTP at /mcp for ChatGPT-style MCP clients.

    The server historically exposed only SSE transport at ``/sse`` (plus
    ``/messages``). OpenAI/ChatGPT MCP connector guidance increasingly
    references the Streamable HTTP transport at ``/mcp``.

    We keep ``/sse`` working for existing clients while also providing ``/mcp``.
    """

    if app_instance is None:
        return

    mcp = getattr(server, "mcp", None)
    http_app_factory = getattr(mcp, "http_app", None)
    if not callable(http_app_factory):
        http_app_factory = getattr(mcp, "streamable_http_app", None)
    if not callable(http_app_factory):
        _register_mcp_fallback_route(app_instance)
        return

    def _build_streamable_app() -> Optional[Any]:
        # Different SDK versions have used different transport names.
        for transport in ("streamable-http", "streamable_http", "http"):
            # Prefer an app rooted at '/' so it can be mounted under '/mcp'.
            for kwargs in (
                {"path": "/", "transport": transport},
                {"transport": transport},
                {"path": "/"},
                {},
            ):
                try:
                    return http_app_factory(**kwargs)
                except TypeError:
                    continue
                except Exception:
                    continue
        return None

    streamable_app = _build_streamable_app()
    if streamable_app is None:
        _register_mcp_fallback_route(app_instance)
        return

    # Avoid double-mounting if a higher-level wrapper already attached /mcp.
    for route in getattr(app_instance, "routes", []) or []:
        if getattr(route, "path", None) == "/mcp":
            return

    try:
        app_instance.mount("/mcp", streamable_app, name="mcp")
    except Exception:
        _register_mcp_fallback_route(app_instance)
        return

    def _has_method(path: str, method: str) -> bool:
        for r in getattr(streamable_app, "routes", []) or []:
            if getattr(r, "path", None) != path:
                continue
            methods = getattr(r, "methods", None) or set()
            if method in methods:
                return True
        return False

    # Provide permissive CORS preflight for connectors and load balancers.
    if not _has_method("/", "OPTIONS"):

        async def _options(_request) -> Response:
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET,HEAD,POST,OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "86400",
                    "Cache-Control": "no-store",
                },
            )

        streamable_app.add_route("/", _options, methods=["OPTIONS"])

    # Some environments probe /mcp with GET/HEAD.
    if not _has_method("/", "GET") or not _has_method("/", "HEAD"):

        async def _probe(_request) -> Response:
            return JSONResponse(
                {
                    "ok": True,
                    "transport": "streamable-http",
                    "endpoint": "/mcp",
                    "hint": "Use this endpoint as the MCP server_url for ChatGPT/OpenAI connectors.",
                    "alternates": {"sse": "/sse", "messages": "/messages"},
                },
                headers={"Cache-Control": "no-store"},
            )

        if not _has_method("/", "GET"):
            streamable_app.add_route("/", _probe, methods=["GET"])
        if not _has_method("/", "HEAD"):
            streamable_app.add_route("/", _probe, methods=["HEAD"])


def _configure_trusted_hosts(app_instance) -> None:
    """Apply a fail-closed Host allowlist to the entire ASGI application."""
    if app_instance is None:
        return
    raw = (
        os.environ.get("ADAPTIV_MCP_ALLOWED_HOSTS")
        or os.environ.get("ALLOWED_HOSTS")
        or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        or ""
    )
    allowed_hosts = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
    if not allowed_hosts:
        allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    app_instance.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


if app is not None:
    _configure_trusted_hosts(app)
if app is not None:
    _try_mount_streamable_http(app)
if app is not None:
    app.add_middleware(_CacheControlMiddleware)
if app is not None:
    app.add_middleware(_RequestContextMiddleware)
if app is not None:
    app.add_middleware(_SuppressClientDisconnectMiddleware)
if app is not None:
    # Auth must be the outermost application middleware so every non-public
    # HTTP route is authenticated before it reaches MCP or tool handlers.
    app.add_middleware(_TransportAuthMiddleware)


async def _handle_value_error(request, exc):
    """Normalize validation errors to a 400 response.

    Starlette raises ``ValueError('Request validation failed')`` for malformed
    inputs; surface that as a plain-text 400 response while re-raising any other
    value errors so they can be handled by the general exception handler.
    """
    if str(exc) == "Request validation failed":
        return PlainTextResponse("Request validation failed", status_code=400)
    raise exc


if app is not None:
    app.add_exception_handler(ValueError, _handle_value_error)


async def _handle_unexpected_error(request, exc):
    """Translate unexpected exceptions into structured MCP error payloads.

    Starlette HTTP exceptions are returned as plain text with their status code.
    All other exceptions are shaped into the MCP error envelope so clients see
    consistent ``error_detail`` data, status codes, and retry headers.
    """
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


def _register_mcp_method_fallbacks(app_instance: Any) -> None:
    """Register GET/OPTIONS fallbacks for FastMCP transport endpoints.

    Some upstream probes and load balancers send GET/HEAD/OPTIONS requests to
    MCP transport endpoints (notably ``/messages`` and ``/sse``). FastMCP only
    registers the strict transport methods (POST for messages, GET for SSE), so
    these probes can generate noisy 405 responses and, in some environments,
    interfere with client capability checks.

    These lightweight handlers avoid 405s while keeping the real transport
    behavior unchanged.
    """
    if app_instance is None or not callable(getattr(app_instance, "add_route", None)):
        return

    def _has_method(path: str, method: str) -> bool:
        for route in getattr(app_instance, "routes", []) or []:
            if getattr(route, "path", None) != path:
                continue
            methods = getattr(route, "methods", None) or set()
            if method in methods:
                return True
        return False

    def _preflight(allow_methods: str) -> Response:
        return Response(
            status_code=204,
            headers={
                # Keep this permissive: most callers are non-browser probes,
                # but allowing CORS preflight avoids surprising failures.
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": allow_methods,
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "600",
            },
        )

    async def _messages_get(_request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "endpoint": "/messages",
                "method": "POST",
                "note": "MCP JSON-RPC endpoint. Send requests via POST.",
            },
            headers={"Cache-Control": "no-store"},
        )

    async def _messages_options(_request) -> Response:
        return _preflight("POST, OPTIONS, GET")

    async def _sse_options(_request) -> Response:
        return _preflight("GET, OPTIONS")

    async def _sse_head(_request) -> Response:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    # FastMCP provides /messages (POST) and /sse (GET). Add method-specific
    # fallbacks without overriding the primary handlers.
    missing_messages_methods = [
        method for method in ("GET", "HEAD") if not _has_method("/messages", method)
    ]
    if missing_messages_methods:
        app_instance.add_route(
            "/messages", _messages_get, methods=missing_messages_methods
        )
    if not _has_method("/messages", "OPTIONS"):
        app_instance.add_route("/messages", _messages_options, methods=["OPTIONS"])
    if not _has_method("/sse", "OPTIONS"):
        app_instance.add_route("/sse", _sse_options, methods=["OPTIONS"])
    if not _has_method("/sse", "HEAD"):
        app_instance.add_route("/sse", _sse_head, methods=["HEAD"])


_register_mcp_method_fallbacks(app)


def _reset_file_cache_for_tests() -> None:
    """Clear the in-memory file cache used by content fetch helpers."""
    clear_cache()


async def terminal_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: str | None = None,
    use_temp_venv: bool = False,
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
    use_temp_venv: bool = False,
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
    use_temp_venv: bool = False,
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
    use_temp_venv: bool = False,
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
    use_temp_venv: bool = False,
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
    """Return a sanitized summary of runtime/server configuration."""
    from github_mcp.main_tools.server_config import get_server_config as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def get_repo_defaults(
    full_name: str | None = None,
) -> dict[str, Any]:
    """Fetch default settings and effective default branch for a repository."""
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
    """Alias for list_render_owners with a render_* prefixed tool name."""
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
    """Alias for list_render_services with a render_* prefixed tool name."""
    return await list_render_services(owner_id=owner_id, cursor=cursor, limit=limit)


@mcp_tool(
    write_action=False,
    name="render_get_service",
    ui={"group": "render", "icon": "🟦", "label": "Get Service", "danger": "low"},
)
async def render_get_service(service_id: str) -> dict[str, Any]:
    """Alias for get_render_service with a render_* prefixed tool name."""
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
    """Alias for list_render_deploys with a render_* prefixed tool name."""
    return await list_render_deploys(service_id=service_id, cursor=cursor, limit=limit)


@mcp_tool(
    write_action=False,
    name="render_get_deploy",
    ui={"group": "render", "icon": "🟦", "label": "Get Deploy", "danger": "low"},
)
async def render_get_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Alias for get_render_deploy with a render_* prefixed tool name."""
    return await get_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_create_deploy",
    open_world_hint=True,
    ui={"group": "render", "icon": "🚀", "label": "Create Deploy", "danger": "high"},
)
async def render_create_deploy(
    service_id: str,
    clear_cache: bool = False,
    commit_id: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Alias for create_render_deploy with a render_* prefixed tool name."""
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
    ui={"group": "render", "icon": "🛑", "label": "Cancel Deploy", "danger": "high"},
)
async def render_cancel_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Alias for cancel_render_deploy with a render_* prefixed tool name."""
    return await cancel_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_rollback_deploy",
    open_world_hint=True,
    ui={"group": "render", "icon": "⏪", "label": "Rollback Deploy", "danger": "high"},
)
async def render_rollback_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    """Alias for rollback_render_deploy with a render_* prefixed tool name."""
    return await rollback_render_deploy(service_id=service_id, deploy_id=deploy_id)


@mcp_tool(
    write_action=True,
    name="render_restart_service",
    open_world_hint=True,
    ui={"group": "render", "icon": "🔁", "label": "Restart Service", "danger": "high"},
)
async def render_restart_service(service_id: str) -> dict[str, Any]:
    """Alias for restart_render_service with a render_* prefixed tool name."""
    return await restart_render_service(service_id=service_id)


@mcp_tool(
    write_action=True,
    name="render_create_service",
    open_world_hint=True,
    ui={"group": "render", "icon": "🧱", "label": "Create Service", "danger": "high"},
)
async def render_create_service(service_spec: dict[str, Any]) -> dict[str, Any]:
    """Alias for create_render_service with a render_* prefixed tool name."""
    return await create_render_service(service_spec=service_spec)


@mcp_tool(
    write_action=False,
    name="render_list_env_vars",
    ui={"group": "render", "icon": "🟦", "label": "List Env Vars", "danger": "low"},
)
async def render_list_env_vars(service_id: str) -> dict[str, Any]:
    """Alias for list_render_service_env_vars with a render_* prefixed tool name."""
    return await list_render_service_env_vars(service_id=service_id)


@mcp_tool(
    write_action=True,
    name="render_set_env_vars",
    open_world_hint=True,
    ui={"group": "render", "icon": "🧪", "label": "Set Env Vars", "danger": "high"},
)
async def render_set_env_vars(
    service_id: str, env_vars: list[dict[str, Any]]
) -> dict[str, Any]:
    """Alias for set_render_service_env_vars with a render_* prefixed tool name."""
    return await set_render_service_env_vars(service_id=service_id, env_vars=env_vars)


@mcp_tool(
    write_action=True,
    name="render_patch_service",
    open_world_hint=True,
    ui={"group": "render", "icon": "🧩", "label": "Patch Service", "danger": "high"},
)
async def render_patch_service(
    service_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Alias for patch_render_service with a render_* prefixed tool name."""
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
    """Alias for get_render_logs with a render_* prefixed tool name."""
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
    """Alias for list_render_logs with a render_* prefixed tool name."""
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
    """Run a PR creation smoke test against the configured controller repo."""
    from github_mcp.main_tools.diagnostics import pr_smoke_test as _impl

    return await _impl(full_name=full_name, base_branch=base_branch, draft=draft)


@mcp_tool(write_action=False)
async def get_rate_limit() -> dict[str, Any]:
    """Return the current GitHub API rate limit status."""
    from github_mcp.main_tools.repositories import get_rate_limit as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def get_user_login() -> dict[str, Any]:
    """Return the authenticated GitHub user for the configured token."""
    from github_mcp.main_tools.repositories import get_user_login as _impl

    return await _impl()


@mcp_tool(write_action=False)
async def list_repositories(
    affiliation: str | None = None,
    visibility: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List repositories visible to the authenticated user."""
    from github_mcp.main_tools.repositories import list_repositories as _impl

    return await _impl(
        affiliation=affiliation, visibility=visibility, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def list_repositories_by_installation(
    installation_id: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """List repositories accessible to a GitHub App installation."""
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
    """Create a new GitHub repository and optionally clone it locally."""
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
    """List recent issues for the authenticated user using filters."""
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
    """List issues in a repository with optional filtering."""
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
    """Fetch a single GitHub issue by number."""
    from github_mcp.main_tools.issues import fetch_issue as _impl

    return await _impl(full_name=full_name, issue_number=issue_number)


@mcp_tool(write_action=False)
async def fetch_issue_comments(
    full_name: str, issue_number: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """Fetch comments for a GitHub issue with pagination."""
    from github_mcp.main_tools.issues import fetch_issue_comments as _impl

    return await _impl(
        full_name=full_name, issue_number=issue_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def fetch_pr(full_name: str, pull_number: int) -> dict[str, Any]:
    """Fetch a single pull request by number."""
    from github_mcp.main_tools.pull_requests import fetch_pr as _impl

    return await _impl(full_name=full_name, pull_number=pull_number)


@mcp_tool(write_action=False)
async def get_pr_info(full_name: str, pull_number: int) -> dict[str, Any]:
    """Return an enriched pull request payload with extra metadata."""
    from github_mcp.main_tools.pull_requests import get_pr_info as _impl

    return await _impl(full_name=full_name, pull_number=pull_number)


@mcp_tool(write_action=False)
async def fetch_pr_comments(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """Fetch review comments for a pull request with pagination."""
    from github_mcp.main_tools.pull_requests import fetch_pr_comments as _impl

    return await _impl(
        full_name=full_name, pull_number=pull_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def list_pr_changed_filenames(
    full_name: str, pull_number: int, per_page: int = 100, page: int = 1
) -> dict[str, Any]:
    """List filenames changed in a pull request."""
    from github_mcp.main_tools.pull_requests import list_pr_changed_filenames as _impl

    return await _impl(
        full_name=full_name, pull_number=pull_number, per_page=per_page, page=page
    )


@mcp_tool(write_action=False)
async def get_commit_combined_status(full_name: str, ref: str) -> dict[str, Any]:
    """Fetch the combined status for a specific commit SHA or ref."""
    from github_mcp.main_tools.pull_requests import get_commit_combined_status as _impl

    return await _impl(full_name=full_name, ref=ref)


@mcp_tool(write_action=False)
async def get_issue_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> dict[str, Any]:
    """Fetch reactions for a specific issue comment."""
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
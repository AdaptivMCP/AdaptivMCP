from __future__ import annotations

import asyncio
import ipaddress
import socket
import sys
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlsplit

from github_mcp.exceptions import UsageError
from github_mcp.http_clients import (
    _external_client_instance as _default_external_client_instance,
    _get_concurrency_semaphore as _default_get_concurrency_semaphore,
)
from github_mcp.server import (
    _github_request as _default_github_request,
    _structured_tool_error as _default_structured_tool_error,
)


def _resolve_main_helper(name: str, default):
    """Resolve an optional helper override from the entry module.

    The server may be executed as `main` or as `__main__` depending on the
    hosting environment. This helper keeps the compatibility surface stable
    without requiring hard imports.
    """
    for mod_name in ("main", "__main__"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    return default


_FETCH_URL_ALLOWED_SCHEMES = {"http", "https"}

# Default cap keeps tool responses predictable and avoids accidental large downloads.
# This can be overridden via env in hosted deployments by patching the constant
# in a wrapper module if needed.
_FETCH_URL_MAX_BYTES = 1_000_000  # 1 MB

# Avoid leaking cookies/tokens set by upstream sites in tool results.
_FETCH_URL_REDACT_RESPONSE_HEADERS = {
    "set-cookie",
    "set-cookie2",
    "proxy-authenticate",
    "www-authenticate",
    "authorization",
    "proxy-authorization",
}


def _is_blocked_hostname(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"}:
        return True
    if host.endswith(".localhost"):
        return True
    if host.endswith(".local"):
        return True
    if host.endswith(".internal"):
        return True
    return False


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Block any non-global addresses (loopback, private RFC1918, link-local,
    # multicast, unspecified, reserved, etc.).
    try:
        return not ip.is_global
    except Exception:
        return True


async def _validate_fetch_url_target(url: str) -> tuple[str, str, int | None]:
    """Validate the URL and prevent SSRF to local/private networks."""

    try:
        parsed = urlsplit(url)
    except Exception as exc:  # noqa: BLE001
        raise UsageError(f"Invalid URL: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in _FETCH_URL_ALLOWED_SCHEMES:
        raise UsageError(
            f"Unsupported URL scheme {scheme!r}. Allowed schemes: {sorted(_FETCH_URL_ALLOWED_SCHEMES)}"
        )

    if parsed.username or parsed.password:
        raise UsageError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise UsageError("URL must include a hostname")

    if _is_blocked_hostname(hostname):
        raise UsageError("Target hostname is not allowed")

    port = parsed.port

    # If hostname is an IP literal, validate directly.
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        if _is_blocked_ip(ip):
            raise UsageError("Target address is not allowed")
        return url, hostname, port

    # Resolve hostname and block any non-global results.
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            hostname,
            port or (443 if scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except Exception as exc:  # noqa: BLE001
        raise UsageError(f"Failed to resolve hostname: {exc}") from exc

    resolved_ips: set[str] = set()
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        # sockaddr can be (host, port) or (host, port, flow, scope)
        try:
            ip_str = sockaddr[0]
        except Exception:
            continue
        resolved_ips.add(ip_str)

    if not resolved_ips:
        raise UsageError("Failed to resolve hostname")

    for ip_str in resolved_ips:
        try:
            candidate = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_blocked_ip(candidate):
            raise UsageError("Target address is not allowed")

    return url, hostname, port


def _sanitize_fetch_url_headers(headers: Dict[str, str]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _FETCH_URL_REDACT_RESPONSE_HEADERS:
            continue
        sanitized[key] = value
    return sanitized


async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a GitHub GraphQL query using the shared HTTP client."""

    github_request = _resolve_main_helper("_github_request", _default_github_request)
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    payload = {"query": query, "variables": variables or {}}
    try:
        result = await github_request(
            "POST",
            "/graphql",
            json_body=payload,
        )
    except Exception as exc:  # noqa: BLE001
        return structured_tool_error(
            exc,
            context="graphql_query",
        )

    # main.py historically returned only the parsed JSON for graphql_query.
    payload_json = result.get("json")
    if isinstance(payload_json, dict):
        return payload_json
    return structured_tool_error(
        RuntimeError("GraphQL response did not include a JSON object"),
        context="graphql_query",
    )


async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an arbitrary HTTP/HTTPS URL via the shared external client."""

    external_client_instance = _resolve_main_helper(
        "_external_client_instance", _default_external_client_instance
    )
    get_concurrency_semaphore = _resolve_main_helper(
        "_get_concurrency_semaphore", _default_get_concurrency_semaphore
    )
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    try:
        await _validate_fetch_url_target(url)
    except UsageError as exc:
        return structured_tool_error(
            exc,
            context="fetch_url",
            path=url,
        )

    client = external_client_instance()
    truncated = False
    content: str = ""
    headers: Dict[str, str] = {}
    status_code: int = 0

    async with get_concurrency_semaphore():
        try:
            # Avoid following redirects to prevent SSRF via Location headers.
            async with client.stream("GET", url, follow_redirects=False) as resp:
                status_code = int(getattr(resp, "status_code", 0) or 0)
                headers = _sanitize_fetch_url_headers(dict(getattr(resp, "headers", {}) or {}))

                collected = bytearray()
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    remaining = _FETCH_URL_MAX_BYTES - len(collected)
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        collected.extend(chunk[:remaining])
                        truncated = True
                        break
                    collected.extend(chunk)

                # Decode best-effort (most endpoints used by assistants are text/JSON).
                try:
                    content = bytes(collected).decode("utf-8", errors="replace")
                except Exception:
                    content = ""
        except Exception as e:  # noqa: BLE001
            return structured_tool_error(
                e,
                context="fetch_url",
                path=url,
            )

    return {
        "status_code": status_code,
        "headers": headers,
        "content": content,
        "truncated": truncated,
        "max_bytes": _FETCH_URL_MAX_BYTES,
    }


async def search(
    query: str,
    search_type: Literal["code", "repositories", "issues", "commits", "users"] = "code",
    per_page: int = 30,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[Literal["asc", "desc"]] = None,
) -> Dict[str, Any]:
    """Perform GitHub search queries (code, repos, issues, commits, or users)."""

    github_request = _resolve_main_helper("_github_request", _default_github_request)
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    allowed_types = {"code", "repositories", "issues", "commits", "users"}
    if search_type not in allowed_types:
        raise ValueError(f"search_type must be one of {sorted(allowed_types)}")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params: Dict[str, Any] = {"q": query, "per_page": per_page, "page": page}
    if sort:
        params["sort"] = sort
    if order is not None:
        allowed_order = {"asc", "desc"}
        if order not in allowed_order:
            raise ValueError("order must be 'asc' or 'desc'")
        params["order"] = order

    headers = None
    if search_type == "commits":
        headers = {
            "Accept": "application/vnd.github+json,application/vnd.github.cloak-preview+json"
        }

    try:
        return await github_request(
            "GET",
            f"/search/{search_type}",
            params=params,
            headers=headers,
        )
    except Exception as exc:  # noqa: BLE001
        return structured_tool_error(
            exc,
            context="search",
        )

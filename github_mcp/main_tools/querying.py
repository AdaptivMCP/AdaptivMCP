from __future__ import annotations

import sys
import ipaddress
import os
import socket
import urllib.parse

from typing import Any, Dict, Literal, Optional

from github_mcp.http_clients import (
    _external_client_instance as _default_external_client_instance,
    _get_concurrency_semaphore as _default_get_concurrency_semaphore,
    _sanitize_response_headers as _default_sanitize_response_headers,
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


async def graphql_query(
    query: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
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


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _get_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _is_ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return True

    # Block anything that isn't globally routable.
    return not addr.is_global


def _host_matches_suffix(host: str, suffixes: list[str]) -> bool:
    h = (host or "").lower().strip().rstrip(".")
    for s in suffixes:
        s2 = s.lower().strip().lstrip(".")
        if not s2:
            continue
        if h == s2 or h.endswith("." + s2):
            return True
    return False


def _validate_external_url(url: str) -> tuple[bool, str]:
    """Block obvious SSRF targets for fetch_url.

    This is a defense-in-depth check. It is intentionally conservative.
    Operators can allow specific hosts via MCP_FETCH_URL_ALLOW_HOSTS or
    MCP_FETCH_URL_ALLOW_HOST_SUFFIXES.
    """

    allow_hosts = {
        h.lower().strip().rstrip(".") for h in _get_csv_env("MCP_FETCH_URL_ALLOW_HOSTS")
    }
    allow_suffixes = _get_csv_env("MCP_FETCH_URL_ALLOW_HOST_SUFFIXES")
    deny_hosts = {
        h.lower().strip().rstrip(".") for h in _get_csv_env("MCP_FETCH_URL_DENY_HOSTS")
    }
    deny_suffixes = _get_csv_env("MCP_FETCH_URL_DENY_HOST_SUFFIXES")

    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in {"http", "https"}:
        return False, "Only http/https URLs are allowed"

    host = (parsed.hostname or "").strip().rstrip(".")
    if not host:
        return False, "URL must include a hostname"

    host_l = host.lower()
    if host_l in deny_hosts or _host_matches_suffix(host_l, deny_suffixes):
        return False, "Host is not allowed"

    # If allowlists are set, require a match.
    if allow_hosts or allow_suffixes:
        if host_l not in allow_hosts and not _host_matches_suffix(
            host_l, allow_suffixes
        ):
            return False, "Host is not in allowlist"

    # Common local/reserved hostnames.
    if host_l in {"localhost", "localhost.localdomain"}:
        return False, "Localhost is not allowed"
    if host_l.endswith(".local") or host_l.endswith(".internal"):
        return False, "Local domains are not allowed"

    # If hostname is an IP literal, validate directly.
    try:
        ipaddress.ip_address(host_l)
        if _is_ip_blocked(host_l):
            return False, "IP address is not allowed"
        return True, ""
    except Exception:
        pass

    # Resolve A/AAAA and reject non-global IPs.
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except Exception:
        return False, "Unable to resolve hostname"

    for family, _socktype, _proto, _canon, sockaddr in infos:
        ip = None
        if family == socket.AF_INET:
            ip = sockaddr[0]
        elif family == socket.AF_INET6:
            ip = sockaddr[0]
        if ip and _is_ip_blocked(ip):
            return False, "Resolved IP is not allowed"

    return True, ""


async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an arbitrary HTTP/HTTPS URL via the shared external client.

    Safety: this tool returns response content. To avoid extremely large payloads
    (and downstream UI/log size limits), content is capped to a maximum number
    of bytes.
    """

    external_client_instance = _resolve_main_helper(
        "_external_client_instance", _default_external_client_instance
    )
    get_concurrency_semaphore = _resolve_main_helper(
        "_get_concurrency_semaphore", _default_get_concurrency_semaphore
    )
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )
    sanitize_response_headers = _resolve_main_helper(
        "_sanitize_response_headers", _default_sanitize_response_headers
    )

    client = external_client_instance()
    max_bytes = _get_int_env("MCP_FETCH_URL_MAX_BYTES", 200_000)
    timeout_s = _get_int_env("MCP_FETCH_URL_TIMEOUT_SECONDS", 30)

    ok, reason = _validate_external_url(url)
    if not ok:
        return {
            "status": "error",
            "message": f"fetch_url blocked: {reason}",
            "url": url,
        }
    async with get_concurrency_semaphore():
        try:
            # Stream to avoid buffering unbounded responses.
            async with client.stream("GET", url, timeout=timeout_s) as resp:
                collected = bytearray()
                truncated = False
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    remaining = max_bytes - len(collected)
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        collected.extend(chunk[:remaining])
                        truncated = True
                        break
                    collected.extend(chunk)

                # Decode best-effort.
                encoding = resp.encoding or "utf-8"
                content = bytes(collected).decode(encoding, errors="replace")

                return {
                    "status_code": resp.status_code,
                    "headers": sanitize_response_headers(resp.headers),
                    "content": content,
                    "content_truncated": truncated,
                    "max_bytes": max_bytes,
                }
        except Exception as e:  # noqa: BLE001
            return structured_tool_error(
                e,
                context="fetch_url",
                path=url,
            )


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

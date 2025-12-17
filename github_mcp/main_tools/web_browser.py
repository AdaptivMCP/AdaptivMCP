from __future__ import annotations

import re
import urllib.parse
from html import unescape
from typing import Any, Dict, List

import httpx

from github_mcp.config import HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE, HTTPX_TIMEOUT
from github_mcp.exceptions import UsageError


_PRIVATE_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}


def _is_blocked_hostname(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return True
    if host in _PRIVATE_HOSTNAMES:
        return True
    if host.endswith(".local"):
        return True

    # Basic private-ip literal blocking.
    # NOTE: We do not DNS-resolve to avoid SSRF-by-DNS complexity.
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        parts = [int(p) for p in host.split(".")]
        if parts[0] == 10:
            return True
        if parts[0] == 127:
            return True
        if parts[0] == 192 and parts[1] == 168:
            return True
        if parts[0] == 169 and parts[1] == 254:
            return True
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return True
    if host.startswith("[") and host.endswith("]"):
        # IPv6 literal (very conservative): block local and ULA.
        inner = host[1:-1].lower()
        if inner == "::1" or inner.startswith("fc") or inner.startswith("fd"):
            return True

    return False


def _validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UsageError("Only http:// and https:// URLs are supported")
    if not parsed.netloc:
        raise UsageError("URL must include a hostname")

    host = parsed.hostname or ""
    if _is_blocked_hostname(host):
        raise UsageError("Blocked hostname (private or local network)")

    return url


def _strip_html_to_text(html: str, *, max_chars: int = 50_000) -> str:
    html = html[:max_chars]

    # Remove script/style blocks.
    html = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", " ", html, flags=re.I | re.S)

    # Replace <br> and </p> with newlines.
    html = re.sub(r"<\s*br\s*/?\s*>", "\n", html, flags=re.I)
    html = re.sub(r"<\s*/\s*p\s*>", "\n", html, flags=re.I)

    # Strip remaining tags.
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)

    # Normalize whitespace.
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def web_fetch(
    url: str,
    *,
    max_chars: int = 80_000,
    strip_html: bool = True,
    user_agent: str = "github-mcp/web-browser",
) -> Dict[str, Any]:
    """Fetch an external URL with conservative SSRF protection and size limits."""

    url = _validate_url(url)

    limits = httpx.Limits(
        max_connections=HTTPX_MAX_CONNECTIONS,
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
    )

    async with httpx.AsyncClient(
        timeout=float(HTTPX_TIMEOUT), limits=limits, follow_redirects=True
    ) as client:
        resp = await client.get(url, headers={"User-Agent": user_agent})

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    # size limits
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    else:
        truncated = False

    extracted_text = _strip_html_to_text(text) if strip_html and "html" in content_type else text

    return {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": content_type,
        "headers": {
            k: v
            for k, v in resp.headers.items()
            if k.lower() in {"content-type", "date", "cache-control"}
        },
        "text": extracted_text,
        "truncated": truncated,
        "strip_html": strip_html,
    }


_DDG_RESULT_RE = re.compile(
    r"<a[^>]+class=\"result__a\"[^>]+href=\"(?P<href>[^\"]+)\"[^>]*>(?P<title>.*?)</a>",
    flags=re.I | re.S,
)

_DDG_SNIPPET_RE = re.compile(
    r"<a[^>]+class=\"result__snippet\"[^>]*>(?P<snippet>.*?)</a>",
    flags=re.I | re.S,
)


def _ddg_extract_results(html: str, *, max_results: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []

    titles = list(_DDG_RESULT_RE.finditer(html))
    snippets = list(_DDG_SNIPPET_RE.finditer(html))

    for idx, m in enumerate(titles[: max_results * 2]):
        href = unescape(m.group("href"))
        title_html = m.group("title")
        title = _strip_html_to_text(title_html, max_chars=2000)

        # duckduckgo wraps redirects as /l/?kh=-1&uddg=<encoded>
        parsed = urllib.parse.urlparse(href)
        if parsed.path.startswith("/l/"):
            qs = urllib.parse.parse_qs(parsed.query)
            uddg = qs.get("uddg", [""])[0]
            if uddg:
                href = urllib.parse.unquote(uddg)

        # pick snippet near the same index when available
        snippet = ""
        if idx < len(snippets):
            snippet = _strip_html_to_text(snippets[idx].group("snippet"), max_chars=4000)

        if href and title:
            results.append({"title": title, "url": href, "snippet": snippet})

        if len(results) >= max_results:
            break

    return results


async def web_search(
    query: str,
    *,
    max_results: int = 8,
    region: str = "us-en",
    safe: str = "moderate",
) -> Dict[str, Any]:
    """Perform a lightweight web search via DuckDuckGo's HTML endpoint."""

    if not query or not query.strip():
        raise UsageError("query must be a non-empty string")

    max_results_int = int(max_results)
    max_results_int = max(1, min(max_results_int, 15))

    params = {
        "q": query,
        "kl": region,
    }

    # safe: off/moderate/strict mapping to ddg safe search params
    safe = (safe or "moderate").strip().lower()
    if safe == "off":
        params["kp"] = "-2"
    elif safe == "strict":
        params["kp"] = "1"
    else:
        params["kp"] = "-1"

    url = "https://duckduckgo.com/html/"

    limits = httpx.Limits(
        max_connections=HTTPX_MAX_CONNECTIONS,
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
    )

    async with httpx.AsyncClient(
        timeout=float(HTTPX_TIMEOUT), limits=limits, follow_redirects=True
    ) as client:
        resp = await client.get(url, params=params, headers={"User-Agent": "github-mcp/web-search"})

    if resp.status_code >= 400:
        raise UsageError(f"Search failed with HTTP {resp.status_code}")

    html = resp.text
    results = _ddg_extract_results(html, max_results=max_results_int)

    return {
        "query": query,
        "engine": "duckduckgo-html",
        "results": results,
        "count": len(results),
    }

"""Helpers for fetching and writing GitHub repository content."""

from __future__ import annotations

import asyncio
import base64
import httpcore
import httpx
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlsplit

from .config import ADAPTIV_MCP_INCLUDE_BASE64_CONTENT, HTTPX_TIMEOUT
from .exceptions import GitHubAPIError
from .http_clients import _external_client_instance, _github_request
from .utils import (
    _effective_ref_for_repo,
    _get_main_module,
    _normalize_repo_path_for_repo,
)


async def _request(*args, **kwargs):
    main_mod = _get_main_module()
    request_fn = getattr(main_mod, "_github_request", _github_request)
    return await request_fn(*args, **kwargs)


async def _verify_file_on_branch(
    full_name: str,
    path: str,
    branch: str,
) -> dict[str, Any]:
    """Verify that a file exists on a specific branch after a write."""

    try:
        decoded = await _decode_github_content(full_name, path, branch)
    except Exception as exc:  # pragma: no cover - defensive
        raise GitHubAPIError(
            f"Post-commit verification failed for {full_name}/{path}@{branch}: {exc}"
        ) from exc

    text = decoded.get("text", "")
    return {
        "full_name": full_name,
        "path": path,
        "branch": branch,
        "verified": True,
        "size": len(text) if isinstance(text, str) else None,
    }


async def _decode_github_content(
    full_name: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any]:
    main_mod = _get_main_module()
    effective_ref_fn = getattr(
        main_mod, "_effective_ref_for_repo", _effective_ref_for_repo
    )
    effective_ref = effective_ref_fn(full_name, ref)
    normalized_path = _normalize_repo_path_for_repo(full_name, path)
    try:
        data = await _request(
            "GET",
            f"/repos/{full_name}/contents/{normalized_path}",
            params={"ref": effective_ref},
        )
    except GitHubAPIError as exc:
        raise GitHubAPIError(
            f"Failed to fetch {full_name}/{normalized_path} at ref '{effective_ref}': {exc}",
            status_code=getattr(exc, "status_code", None),
            response_payload=getattr(exc, "response_payload", None),
        ) from exc
    if not isinstance(data.get("json"), dict):
        raise GitHubAPIError("Unexpected content response shape from GitHub")

    j = data["json"]

    # GitHub's Contents API may omit `content` for large files and instead
    # return metadata such as `size`, `sha`, and `download_url`.
    content = j.get("content")
    encoding = j.get("encoding")
    if not isinstance(content, str) or not isinstance(encoding, str):
        size = j.get("size")
        return {
            "json": j,
            "content": None,
            "encoding": None,
            "sha": j.get("sha"),
            "text": None,
            "decoded_bytes": None,
            "size": size if isinstance(size, int) else None,
            "large_file": True,
            "message": (
                "GitHub did not return inline content for this file (commonly due to size). "
                "get_file_excerpt provides range-based access."
            ),
        }

    try:
        decoded = base64.b64decode(content)
    except Exception as exc:
        raise GitHubAPIError("Failed to decode GitHub content") from exc

    decoded_len = len(decoded)
    stored_bytes: bytes | None = decoded

    text: str | None = None
    if stored_bytes is not None:
        try:
            text = stored_bytes.decode("utf-8")
        except Exception:
            text = None

    response: dict[str, Any] = {
        "json": j,
        "content": content if ADAPTIV_MCP_INCLUDE_BASE64_CONTENT else None,
        "encoding": encoding if ADAPTIV_MCP_INCLUDE_BASE64_CONTENT else None,
        "sha": j.get("sha"),
        "text": text,
        "decoded_bytes": stored_bytes,
        "size": decoded_len,
    }
    return response


async def _get_branch_sha(full_name: str, branch: str) -> str:
    data = await _request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
    if not isinstance(data.get("json"), dict):
        raise GitHubAPIError("Unexpected ref response when fetching branch SHA")
    sha = data["json"].get("object", {}).get("sha")
    if not sha:
        raise GitHubAPIError("Missing SHA in branch ref response")
    return sha


async def _resolve_file_sha(full_name: str, path: str, branch: str) -> str | None:
    try:
        decoded = await _decode_github_content(full_name, path, branch)
        sha = decoded.get("json", {}).get("sha")
        if not isinstance(sha, str):
            return None
        return sha
    except GitHubAPIError:
        return None


def _strip_large_fields_from_commit_response(
    response_json: dict[str, Any],
) -> dict[str, Any]:
    """Remove large fields from GitHub Contents API responses.

    The GitHub Contents write endpoints often return base64-encoded file bodies in
    `response_json['content']['content']`. Returning that blob to clients can
    explode tool payload sizes and cause disconnects or network errors.

    We keep the rest of the response (sha, html_url, commit sha, etc.).
    """

    if not isinstance(response_json, dict):
        return response_json

    cleaned: dict[str, Any] = dict(response_json)
    content = cleaned.get("content")
    if isinstance(content, dict):
        content_clean = dict(content)
        content_clean.pop("content", None)
        content_clean.pop("encoding", None)
        cleaned["content"] = content_clean

    return cleaned


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
    if not isinstance(body_bytes, (bytes, bytearray)):
        raise TypeError("body_bytes must be bytes")

    normalized_path = _normalize_repo_path_for_repo(full_name, path)
    content_b64 = base64.b64encode(body_bytes).decode("ascii")
    payload: dict[str, Any] = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    if committer:
        payload["committer"] = committer
    if author:
        payload["author"] = author

    result = await _request(
        "PUT",
        f"/repos/{full_name}/contents/{normalized_path}",
        json_body=payload,
    )
    if not isinstance(result.get("json"), dict):
        raise GitHubAPIError("Unexpected commit response from GitHub")
    return _strip_large_fields_from_commit_response(result["json"])


def _allowed_content_hosts() -> set[str]:
    raw = os.getenv("ADAPTIV_MCP_ALLOWED_CONTENT_HOSTS", "")
    configured = {
        host.strip().lower().rstrip(".")
        for host in raw.replace(",", " ").split()
        if host.strip()
    }
    # GitHub content hosts are the only built-in remote destinations. Additional
    # destinations must be explicitly configured; arbitrary LLM-supplied URLs
    # are not trusted by default.
    return configured | {"github.com", "raw.githubusercontent.com"}


class _PinnedDNSBackend(httpcore.AsyncNetworkBackend):
    """Connect to an already-validated address while preserving HTTP Host/SNI."""

    def __init__(self, ip: str) -> None:
        self._ip = ip
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_tcp(
            self._ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_unix_socket(path, timeout=timeout)

    async def sleep(self, seconds: float = 0.0) -> None:
        await self._backend.sleep(seconds)


class _PinnedHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport that pins TCP connections to a validated DNS address."""

    def __init__(self, ip: str) -> None:
        super().__init__()
        self._pool._network_backend = _PinnedDNSBackend(ip)


async def _resolve_content_url(content_url: str) -> tuple[str, str]:
    """Validate a remote content URL before the server makes an outbound request.

    This is an SSRF boundary: only HTTP(S), approved hosts, no URL userinfo,
    and public DNS results are permitted. Redirects are disabled separately
    at the HTTP client call site.
    """
    try:
        parsed = urlsplit(content_url)
    except ValueError as exc:
        raise GitHubAPIError("Invalid content_url") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise GitHubAPIError("content_url must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise GitHubAPIError("content_url must not contain credentials")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or hostname not in _allowed_content_hosts():
        raise GitHubAPIError(
            f"content_url host is not allowed: {hostname or '<missing>'}"
        )
    if parsed.port not in (None, 80, 443):
        raise GitHubAPIError("content_url must use the default HTTP(S) port")

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise GitHubAPIError("content_url hostname could not be resolved") from exc

    ips = {item[4][0] for item in addresses if item[4]}
    if not ips:
        raise GitHubAPIError("content_url hostname did not resolve")

    for raw_ip in ips:
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise GitHubAPIError("content_url resolved to an invalid IP") from exc
        if not ip.is_global:
            raise GitHubAPIError("content_url resolved to a non-public IP")

    return content_url, sorted(ips)[0]


async def _validate_content_url(content_url: str) -> str:
    validated_url, _ = await _resolve_content_url(content_url)
    return validated_url


async def _load_body_from_content_url(content_url: str, *, context: str) -> bytes:
    """Read bytes from an absolute path, HTTP(S) URL, or GitHub URL."""

    if not isinstance(content_url, str) or not content_url.strip():
        raise ValueError("content_url must be a non-empty string when provided")

    content_url = content_url.strip()

    if content_url.startswith("github:"):
        spec = content_url[len("github:") :].strip()
        if not spec:
            raise GitHubAPIError(
                "github: content_url must include owner/repo:path[@ref]"
            )

        if "/" not in spec or ":" not in spec:
            raise GitHubAPIError("github: content_url must be owner/repo:path[@ref]")

        owner_repo, path_ref = spec.split(":", 1)
        if "/" not in owner_repo or not path_ref:
            raise GitHubAPIError("github: content_url must be owner/repo:path[@ref]")

        full_name = owner_repo
        path_part, _, ref = path_ref.partition("@")
        if not path_part:
            raise GitHubAPIError(
                "github: content_url must specify a file path after ':'"
            )

        decoded = await _decode_github_content(
            full_name=full_name,
            path=path_part,
            ref=ref or None,
        )
        decoded_bytes = decoded.get("decoded_bytes")
        if not isinstance(decoded_bytes, (bytes, bytearray)):
            raise GitHubAPIError("github: decoded content did not return bytes")
        if isinstance(decoded_bytes, bytearray):
            return bytes(decoded_bytes)
        return decoded_bytes

    def _allowed_local_content_roots() -> list[str]:
        raw = os.getenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", "")
        roots: list[str] = []
        for value in raw.replace(",", " ").split():
            try:
                root = os.path.realpath(os.path.abspath(value))
            except (OSError, ValueError):
                continue
            roots.append(root)
        return roots

    def _read_local(local_path: str) -> bytes:
        allowed_roots = _allowed_local_content_roots()
        if not allowed_roots:
            raise GitHubAPIError(
                "Local content_url reads are disabled unless "
                "ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS is configured."
            )

        try:
            resolved_path = os.path.realpath(os.path.abspath(local_path))
        except (OSError, ValueError) as exc:
            raise GitHubAPIError("Invalid local content_url path") from exc

        if not any(
            resolved_path == root or resolved_path.startswith(root + os.sep)
            for root in allowed_roots
        ):
            raise GitHubAPIError(
                "content_url local file is outside the configured local content roots"
            )

        try:
            with open(resolved_path, "rb") as f:
                return f.read()
        except FileNotFoundError as exc:
            err = GitHubAPIError(
                f"{context} content_url path not found at {resolved_path}."
            )
            raise err from exc
        except OSError as exc:
            raise GitHubAPIError(
                f"Failed to read content_url from {resolved_path}: {exc}"
            ) from exc

    def _is_windows_absolute_path(path: str) -> bool:
        if not isinstance(path, str) or len(path) < 3:
            return False
        # UNC path
        if path.startswith("\\\\"):
            return True
        # Drive letter + : + separator
        letter = path[0]
        if not ("A" <= letter <= "Z" or "a" <= letter <= "z"):
            return False
        if path[1] != ":":
            return False
        return path[2] in ("\\", "/")

    if content_url.startswith("/") or _is_windows_absolute_path(content_url):
        return _read_local(content_url)

    if content_url.startswith("http://") or content_url.startswith("https://"):
        validated_url, validated_ip = await _resolve_content_url(content_url)
        client = _external_client_instance()
        if isinstance(client, httpx.AsyncClient):
            async with httpx.AsyncClient(
                transport=_PinnedHTTPTransport(validated_ip),
                timeout=HTTPX_TIMEOUT,
            ) as pinned_client:
                response = await pinned_client.get(
                    validated_url, follow_redirects=False
                )
        else:
            # Preserve injectable test clients and other compatible clients.
            response = await client.get(validated_url, follow_redirects=False)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"Failed to fetch content from {content_url}: {response.status_code}"
            )
        return response.content

    raise GitHubAPIError(
        f"{context} content_url must be an absolute http(s) URL, a github: URL, "
        "or an absolute local file path."
    )


__all__ = [
    "_decode_github_content",
    "_get_branch_sha",
    "_load_body_from_content_url",
    "_perform_github_commit",
    "_resolve_file_sha",
    "_verify_file_on_branch",
]

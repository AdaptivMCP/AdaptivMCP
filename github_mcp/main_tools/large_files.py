"""Helpers for working with large repository files.

GitHub's Contents API often omits inline base64 content for large files.
Additionally, returning multi-megabyte payloads over MCP is rarely useful and
can cause client/server instability.

This module provides range-based access to file content so callers can inspect
large files safely.
"""

from __future__ import annotations

from typing import Any

from github_mcp.exceptions import GitHubAPIError
from github_mcp.http_clients import _github_client_instance
from github_mcp.server import _github_request
from github_mcp.utils import (
    _effective_ref_for_repo,
    _normalize_repo_path_for_repo,
    _with_numbered_lines,
)


def _build_range_header(
    *,
    start_byte: int | None,
    max_bytes: int,
    tail_bytes: int | None,
) -> str:
    # max_bytes <= 0 disables byte caps.
    # When disabled:
    # - start_byte -> open-ended range "bytes=<start>-"
    # - tail_bytes -> suffix range "bytes=-<tail>"
    # - neither -> no Range header (caller may fetch full file)

    if start_byte is not None and start_byte < 0:
        raise ValueError("start_byte must be >= 0")

    if tail_bytes is not None and tail_bytes <= 0:
        raise ValueError("tail_bytes must be > 0")

    if start_byte is not None and tail_bytes is not None:
        raise ValueError("Provide only one of start_byte or tail_bytes")

    if max_bytes <= 0:
        if tail_bytes is not None:
            return f"bytes=-{tail_bytes}"
        if start_byte is not None:
            return f"bytes={start_byte}-"
        return ""

    # Default is a "head" read.
    if start_byte is None and tail_bytes is None:
        start_byte = 0

    if tail_bytes is not None:
        # RFC 9110: suffix-byte-range-spec.
        return f"bytes=-{min(tail_bytes, max_bytes)}"

    end_byte = start_byte + max_bytes - 1
    return f"bytes={start_byte}-{end_byte}"


async def _get_content_metadata(
    *,
    full_name: str,
    path: str,
    ref: str,
) -> dict[str, Any]:
    """Best-effort fetch of file metadata without returning the full body."""

    try:
        data = await _github_request(
            "GET",
            f"/repos/{full_name}/contents/{path}",
            params={"ref": ref},
        )
    except Exception:
        return {}

    j = data.get("json")
    if not isinstance(j, dict):
        return {}

    size = j.get("size")
    sha = j.get("sha")
    download_url = j.get("download_url")
    return {
        "sha": sha if isinstance(sha, str) else None,
        "size": size if isinstance(size, int) else None,
        "download_url": download_url if isinstance(download_url, str) else None,
        "type": j.get("type") if isinstance(j.get("type"), str) else None,
    }


async def get_file_excerpt(
    *,
    full_name: str,
    path: str,
    ref: str = "main",
    start_byte: int | None = None,
    max_bytes: int = 0,
    tail_bytes: int | None = None,
    as_text: bool = True,
    max_text_chars: int = 0,
    numbered_lines: bool = True,
) -> dict[str, Any]:
    """Fetch a bounded excerpt of a repository file.

    The excerpt is fetched using the GitHub Contents endpoint with
    "application/vnd.github.raw" so the server streams raw bytes.
    When the upstream does not honor Range, this function still caps the
    returned payload size.
    """

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_path = _normalize_repo_path_for_repo(full_name, path)

    range_header = _build_range_header(
        start_byte=start_byte,
        max_bytes=max_bytes,
        tail_bytes=tail_bytes,
    )

    headers = {"Accept": "application/vnd.github.raw"}
    if range_header:
        headers["Range"] = range_header

    client = _github_client_instance()
    body = bytearray()
    truncated = False
    response_headers: dict[str, Any] = {}

    # Stream to avoid loading large responses into memory.
    try:
        async with client.stream(
            "GET",
            f"/repos/{full_name}/contents/{normalized_path}",
            params={"ref": effective_ref},
            headers=headers,
        ) as resp:
            response_headers = dict(getattr(resp, "headers", {}) or {})
            if resp.status_code >= 400:
                message = None
                try:
                    payload = resp.json()
                    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                        message = payload.get("message")
                except Exception:
                    message = None
                suffix = f" - {message}" if message else ""
                raise GitHubAPIError(
                    "Failed to fetch raw content for "
                    f"{full_name}/{normalized_path}@{effective_ref}: "
                    f"HTTP {resp.status_code}{suffix}"
                )

            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                if max_bytes and max_bytes > 0:
                    remaining = max_bytes - len(body)
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        body.extend(chunk[:remaining])
                        truncated = True
                        break
                body.extend(chunk)
    except GitHubAPIError:
        raise
    except Exception as exc:
        raise GitHubAPIError(
            f"Failed to stream content for {full_name}/{normalized_path}: {exc}"
        ) from exc

    content_bytes = bytes(body)
    text: str | None = None
    numbered: str | None = None
    if as_text:
        text = content_bytes.decode("utf-8", errors="replace")
        if max_text_chars > 0 and len(text) > max_text_chars:
            text = text[:max_text_chars]
        if numbered_lines:
            numbered = _with_numbered_lines(text)

    metadata = await _get_content_metadata(
        full_name=full_name,
        path=normalized_path,
        ref=effective_ref,
    )

    return {
        "full_name": full_name,
        "path": normalized_path,
        "ref": effective_ref,
        "range_requested": range_header,
        "status_code": None,
        "headers": {
            # Return a curated subset to avoid exploding payload size.
            "content_range": response_headers.get("Content-Range"),
            "accept_ranges": response_headers.get("Accept-Ranges"),
            "etag": response_headers.get("ETag"),
            "content_length": response_headers.get("Content-Length"),
        },
        "size": len(content_bytes),
        "truncated": truncated,
        "bytes_base64": None,
        "text": text,
        "numbered_lines": numbered,
        "metadata": metadata,
        "note": (
            "If tail_bytes was requested but the upstream did not honor Range, "
            "the returned excerpt may not represent the file tail."
            if tail_bytes is not None
            else None
        ),
    }


__all__ = ["get_file_excerpt"]

"""Helpers for fetching and writing GitHub repository content."""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional

import httpx

from . import config
from .exceptions import GitHubAPIError
from .http_clients import _github_request
from .utils import _effective_ref_for_repo


async def _verify_file_on_branch(
    full_name: str,
    path: str,
    branch: str,
) -> Dict[str, Any]:
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
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    effective_ref = _effective_ref_for_repo(full_name, ref)
    try:
        data = await _github_request(
            "GET",
            f"/repos/{full_name}/contents/{path}",
            params={"ref": effective_ref},
        )
    except GitHubAPIError as exc:
        raise GitHubAPIError(
            f"Failed to fetch {full_name}/{path} at ref '{effective_ref}': {exc}"
        ) from exc
    if not isinstance(data.get("json"), dict):
        raise GitHubAPIError("Unexpected content response shape from GitHub")

    j = data["json"]
    content = j.get("content")
    encoding = j.get("encoding")
    if not isinstance(content, str) or not isinstance(encoding, str):
        raise GitHubAPIError("Missing content/encoding in GitHub response")

    try:
        decoded = base64.b64decode(content)
    except Exception as exc:
        raise GitHubAPIError("Failed to decode GitHub content") from exc

    text: Optional[str] = None
    try:
        text = decoded.decode("utf-8")
    except Exception:
        text = None

    return {
        "json": j,
        "content": content,
        "encoding": encoding,
        "text": text,
        "decoded_bytes": decoded,
    }


async def _get_branch_sha(full_name: str, branch: str) -> str:
    data = await _github_request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
    if not isinstance(data.get("json"), dict):
        raise GitHubAPIError("Unexpected ref response when fetching branch SHA")
    sha = data["json"].get("object", {}).get("sha")
    if not sha:
        raise GitHubAPIError("Missing SHA in branch ref response")
    return sha


async def _resolve_file_sha(full_name: str, path: str, branch: str) -> Optional[str]:
    try:
        decoded = await _decode_github_content(full_name, path, branch)
        sha = decoded.get("json", {}).get("sha")
        if not isinstance(sha, str):
            return None
        return sha
    except GitHubAPIError:
        return None


async def _perform_github_commit(
    full_name: str,
    *,
    branch: str,
    path: str,
    message: str,
    content_b64: str,
    sha: Optional[str],
    committer: Optional[Dict[str, str]] = None,
    author: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    if committer:
        payload["committer"] = committer
    if author:
        payload["author"] = author

    result = await _github_request(
        "PUT",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
    )
    if not isinstance(result.get("json"), dict):
        raise GitHubAPIError("Unexpected commit response from GitHub")
    return result["json"]


async def _load_body_from_content_url(url: str) -> bytes:
    if not url.startswith(config.GITHUB_API_BASE):
        raise GitHubAPIError(
            "Content URL must start with the configured GitHub API base URL"
        )

    client = httpx.AsyncClient(base_url=config.GITHUB_API_BASE)
    try:
        resp = await client.get(url.replace(config.GITHUB_API_BASE, ""))
        resp.raise_for_status()
        return resp.content
    finally:
        await client.aclose()


__all__ = [
    "_decode_github_content",
    "_get_branch_sha",
    "_load_body_from_content_url",
    "_perform_github_commit",
    "_resolve_file_sha",
    "_verify_file_on_branch",
]

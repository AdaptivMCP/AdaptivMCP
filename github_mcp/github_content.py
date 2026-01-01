"""Helpers for fetching and writing GitHub repository content."""

from __future__ import annotations

import base64
import re
import sys
from typing import Any, Dict, Optional

from .config import SANDBOX_CONTENT_BASE_URL
from .exceptions import GitHubAPIError
from .http_clients import _external_client_instance, _github_request
from .utils import _effective_ref_for_repo, _get_main_module


async def _request(*args, **kwargs):
    main_mod = _get_main_module()
    request_fn = getattr(main_mod, "_github_request", _github_request)
    return await request_fn(*args, **kwargs)


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
    main_mod = _get_main_module()
    effective_ref_fn = getattr(
        main_mod, "_effective_ref_for_repo", _effective_ref_for_repo
    )
    effective_ref = effective_ref_fn(full_name, ref)
    try:
        data = await _request(
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
        "sha": j.get("sha"),
        "text": text,
        "decoded_bytes": decoded,
    }


async def _get_branch_sha(full_name: str, branch: str) -> str:
    data = await _request("GET", f"/repos/{full_name}/git/ref/heads/{branch}")
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



def _strip_large_fields_from_commit_response(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Remove large fields from GitHub Contents API responses.

    The GitHub Contents write endpoints often return base64-encoded file bodies in
    `response_json['content']['content']`. Returning that blob to ChatGPT can
    explode tool payload sizes and cause client disconnects/network errors.

    We keep the rest of the response (sha, html_url, commit sha, etc.).
    """

    if not isinstance(response_json, dict):
        return response_json

    cleaned: Dict[str, Any] = dict(response_json)
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
    sha: Optional[str],
    committer: Optional[Dict[str, str]] = None,
    author: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if not isinstance(body_bytes, (bytes, bytearray)):
        raise TypeError("body_bytes must be bytes")

    content_b64 = base64.b64encode(body_bytes).decode("ascii")
    payload: Dict[str, Any] = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    if committer:
        payload["committer"] = committer
    if author:
        payload["author"] = author

    result = await _request(
        "PUT",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
    )
    if not isinstance(result.get("json"), dict):
        raise GitHubAPIError("Unexpected commit response from GitHub")
    return _strip_large_fields_from_commit_response(result["json"])


async def _load_body_from_content_url(content_url: str, *, context: str) -> bytes:
    """Read bytes from a sandbox path, absolute path, HTTP(S) URL, or GitHub URL."""

    if not isinstance(content_url, str) or not content_url.strip():
        raise ValueError("content_url must be a non-empty string when provided")

    content_url = content_url.strip()

    if content_url.startswith("github:"):
        spec = content_url[len("github:") :].strip()
        if not spec:
            raise GitHubAPIError("github: content_url must include owner/repo:path[@ref]")

        if "/" not in spec or ":" not in spec:
            raise GitHubAPIError("github: content_url must be owner/repo:path[@ref]")

        owner_repo, path_ref = spec.split(":", 1)
        if "/" not in owner_repo or not path_ref:
            raise GitHubAPIError("github: content_url must be owner/repo:path[@ref]")

        full_name = owner_repo
        path_part, _, ref = path_ref.partition("@")
        if not path_part:
            raise GitHubAPIError("github: content_url must specify a file path after ':'")

        decoded = await _decode_github_content(
            full_name=full_name,
            path=path_part,
            ref=ref or None,
        )
        decoded_bytes = decoded.get("decoded_bytes")
        if not isinstance(decoded_bytes, (bytes, bytearray)):
            raise GitHubAPIError("github: decoded content did not return bytes")
        return decoded_bytes

    def _read_local(local_path: str, missing_hint: str) -> bytes:
        try:
            with open(local_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            raise GitHubAPIError(
                f"{context} content_url path not found at {local_path}. {missing_hint}"
            )
        except OSError as e:
            raise GitHubAPIError(f"Failed to read content_url from {local_path}: {e}")

    async def _fetch_rewritten_path(local_path: str, *, base_url: str) -> bytes:
        rewritten_url = base_url.rstrip("/") + "/" + local_path.lstrip("/")
        client = _external_client_instance()
        response = await client.get(rewritten_url)
        if response.status_code >= 400:
            snippet = response.text[:500]
            raise GitHubAPIError(
                f"Failed to fetch content from rewritten sandbox URL {rewritten_url}: "
                f"{response.status_code}. Response: {snippet}"
            )
        return response.content

    sandbox_hint = (
        "If you are running inside ChatGPT, ensure the file exists in the sandbox "
        "and pass the full sandbox:/ path so the host can rewrite it to an "
        "accessible URL."
    )

    def _is_windows_absolute_path(path: str) -> bool:
        return bool(re.match(r"^[a-zA-Z]:[\\/].*", path) or path.startswith("\\\\"))

    if content_url.startswith("sandbox:"):
        local_path = content_url[len("sandbox:") :]
        rewrite_base = SANDBOX_CONTENT_BASE_URL
        try:
            return _read_local(local_path, sandbox_hint)
        except GitHubAPIError:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(local_path, base_url=rewrite_base)
            raise GitHubAPIError(
                f"{context} content_url path not found at {local_path}. "
                "Provide an http(s) URL that already points to the sandbox file "
                "or configure SANDBOX_CONTENT_BASE_URL so the server can fetch it "
                "when direct filesystem access is unavailable."
            )

    if content_url.startswith("/") or _is_windows_absolute_path(content_url):
        rewrite_base = SANDBOX_CONTENT_BASE_URL
        missing_hint = (
            "If this was meant to be a sandbox file, prefix it with sandbox:/ so "
            "hosts can rewrite it."
        )
        try:
            return _read_local(content_url, missing_hint)
        except GitHubAPIError:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(content_url, base_url=rewrite_base)
            raise GitHubAPIError(
                f"{context} content_url path not found at {content_url}. "
                f"{missing_hint} Configure SANDBOX_CONTENT_BASE_URL or provide an "
                "absolute http(s) URL so the server can fetch the sandbox file when "
                "it is not mounted locally."
            )

    if content_url.startswith("http://") or content_url.startswith("https://"):
        client = _external_client_instance()
        response = await client.get(content_url)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"Failed to fetch content from {content_url}: {response.status_code}"
            )
        return response.content

    raise GitHubAPIError(
        f"{context} content_url must be an absolute http(s) URL, a sandbox:/ path, "
        "or an absolute local file path. In ChatGPT, pass the sandbox file path "
        "(e.g. sandbox:/mnt/data/file) and the host will rewrite it to a real URL "
        "before it reaches this server."
    )


__all__ = [
    "_decode_github_content",
    "_get_branch_sha",
    "_load_body_from_content_url",
    "_perform_github_commit",
    "_resolve_file_sha",
    "_verify_file_on_branch",
]

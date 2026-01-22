"""Helpers for fetching and writing GitHub repository content."""

from __future__ import annotations

import base64
from typing import Any

from .config import (
    ADAPTIV_MCP_INCLUDE_BASE64_CONTENT,
    SANDBOX_CONTENT_BASE_URL,
)
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
    effective_ref_fn = getattr(main_mod, "_effective_ref_for_repo", _effective_ref_for_repo)
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
    `response_json['content']['content']`. Returning that blob to ChatGPT can
    explode tool payload sizes and cause client disconnects/network errors.

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
        except FileNotFoundError as exc:
            err = GitHubAPIError(f"{context} content_url path not found at {local_path}.")
            if missing_hint:
                # Keep hints separate from the primary error message so clients
                # can render them without triggering repetitive LLM behaviors.
                err.hint = str(missing_hint).strip()
            raise err from exc
        except OSError as exc:
            raise GitHubAPIError(f"Failed to read content_url from {local_path}: {exc}") from exc

    async def _fetch_rewritten_path(local_path: str, *, base_url: str) -> bytes:
        rewritten_url = base_url.rstrip("/") + "/" + local_path.lstrip("/")
        client = _external_client_instance()
        response = await client.get(rewritten_url)
        if response.status_code >= 400:
            snippet = response.text
            raise GitHubAPIError(
                f"Failed to fetch content from rewritten sandbox URL {rewritten_url}: "
                f"{response.status_code}. Response: {snippet}"
            )
        return response.content

    sandbox_hint = (
        "In ChatGPT-hosted environments, local files live in the runtime sandbox. "
        "The sandbox:/ prefix allows the host to rewrite the local path into an "
        "accessible URL when direct filesystem access is unavailable."
    )

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

    if content_url.startswith("sandbox:"):
        local_path = content_url[len("sandbox:") :]
        rewrite_base = SANDBOX_CONTENT_BASE_URL
        try:
            return _read_local(local_path, sandbox_hint)
        except GitHubAPIError as exc:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(local_path, base_url=rewrite_base)
            err = GitHubAPIError(
                f"{context} content_url path not found at {local_path}. "
                "Provide an http(s) URL that already points to the sandbox file "
                "or configure SANDBOX_CONTENT_BASE_URL so the server can fetch it "
                "when direct filesystem access is unavailable."
            )
            # Preserve the sandbox hint in a structured field without duplicating
            # it in the primary error message.
            err.hint = getattr(exc, "hint", None) or sandbox_hint
            raise err from exc

    if content_url.startswith("/") or _is_windows_absolute_path(content_url):
        rewrite_base = SANDBOX_CONTENT_BASE_URL
        missing_hint = (
            "If this was meant to be a sandbox file, prefix it with sandbox:/ so "
            "hosts can rewrite it."
        )
        try:
            return _read_local(content_url, missing_hint)
        except GitHubAPIError as exc:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(content_url, base_url=rewrite_base)
            err = GitHubAPIError(
                f"{context} content_url path not found at {content_url}. "
                "Configure SANDBOX_CONTENT_BASE_URL or provide an absolute http(s) URL "
                "so the server can fetch the sandbox file when it is not mounted locally."
            )
            if missing_hint:
                err.hint = str(missing_hint).strip()
            raise err from exc

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

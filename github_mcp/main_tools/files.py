from __future__ import annotations

from typing import Any, NotRequired, TypedDict

import github_mcp.config as config
from github_mcp.diff_utils import build_unified_diff
from github_mcp.utils import _normalize_write_context, extract_sha, require_text
from github_mcp.write_logging import log_write_diff

from ._main import _main


class WriteVerification(TypedDict):
    sha_before: str | None
    sha_after: str | None
    html_url: str | None


class WriteResultBase(TypedDict):
    full_name: str
    path: str
    branch: str
    message: str
    commit: Any
    verification: WriteVerification


class WriteResultCreated(WriteResultBase):
    status: str
    diff: NotRequired[str | None]


class WriteResultCommitted(WriteResultBase):
    status: str
    diff: NotRequired[str | None]


class WriteResultMoved(TypedDict):
    status: str
    full_name: str
    branch: str
    from_path: str
    to_path: str
    write_result: WriteResultCommitted
    delete_result: dict[str, Any]


async def create_file(
    full_name: str,
    path: str,
    content: str,
    *,
    branch: str = "main",
    message: str | None = None,
    return_diff: bool = False,
) -> WriteResultCreated:
    """Create a new text file in a repository after normalizing path and branch."""

    m = _main()

    effective_branch, normalized_path = _normalize_write_context(full_name, branch, path)
    if normalized_path is None:
        raise ValueError("path must not be empty after normalization")

    # Ensure the file does not already exist.
    try:
        await m._decode_github_content(full_name, normalized_path, effective_branch)
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        if getattr(exc, "status_code", None) == 404:
            sha_before: str | None = None
        else:
            raise
    else:
        raise m.GitHubAPIError(  # type: ignore[attr-defined]
            f"File already exists at {normalized_path} on branch {effective_branch}"
        )

    body_bytes = content.encode("utf-8")
    commit_message = message or f"Create {normalized_path}"

    commit_result = await m._perform_github_commit(
        full_name=full_name,
        path=normalized_path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    verified = await m._decode_github_content(full_name, normalized_path, effective_branch)
    sha_after = extract_sha(verified)

    # Render-log friendly diff logging (colored additions/removals).
    full_diff = build_unified_diff(
        "",
        content,
        fromfile=f"a/{normalized_path}",
        tofile=f"b/{normalized_path}",
    )
    log_write_diff("Created", full_name=full_name, path=normalized_path, diff_text=full_diff)

    diff_text: str | None = None
    if return_diff:
        diff_text = full_diff

    return {
        "status": "created",
        "full_name": full_name,
        "path": normalized_path,
        "branch": effective_branch,
        "message": commit_message,
        "commit": commit_result,
        "verification": {
            "sha_before": sha_before,
            "sha_after": sha_after,
            "html_url": verified.get("html_url"),
        },
        **({"diff": diff_text} if return_diff else {}),
    }


async def apply_text_update_and_commit(
    full_name: str,
    path: str,
    updated_content: str,
    *,
    branch: str = "main",
    message: str | None = None,
    return_diff: bool = False,
) -> WriteResultCommitted:
    """Apply a text update to a single file on a branch, then verify it."""

    m = _main()

    effective_branch, normalized_path = _normalize_write_context(full_name, branch, path)
    if normalized_path is None:
        raise ValueError("path must not be empty after normalization")

    is_new_file = False
    old_text: str | None = None

    try:
        decoded = await m._decode_github_content(full_name, normalized_path, effective_branch)
        old_text = require_text(decoded)
        sha_before = extract_sha(decoded)
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        if getattr(exc, "status_code", None) == 404:
            is_new_file = True
            sha_before = None
            old_text = ""
        else:
            raise

    body_bytes = updated_content.encode("utf-8")
    if message is not None:
        commit_message = message
    elif is_new_file:
        commit_message = f"Create {normalized_path}"
    else:
        commit_message = f"Update {normalized_path}"

    commit_result = await m._perform_github_commit(
        full_name=full_name,
        path=normalized_path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    verified = await m._decode_github_content(full_name, normalized_path, effective_branch)
    sha_after = extract_sha(verified)

    # Render-log friendly diff logging (colored additions/removals).
    before = old_text or ""
    after = updated_content
    full_diff = build_unified_diff(
        before,
        after,
        fromfile=f"a/{normalized_path}",
        tofile=f"b/{normalized_path}",
    )
    log_write_diff("Committed", full_name=full_name, path=normalized_path, diff_text=full_diff)

    diff_text: str | None = None
    if return_diff:
        diff_text = full_diff

    return {
        "status": "committed",
        "full_name": full_name,
        "path": normalized_path,
        "branch": effective_branch,
        "message": commit_message,
        "commit": commit_result,
        "verification": {
            "sha_before": sha_before,
            "sha_after": sha_after,
            "html_url": verified.get("html_url"),
        },
        **({"diff": diff_text} if return_diff else {}),
    }


async def move_file(
    full_name: str,
    from_path: str,
    to_path: str,
    branch: str = "main",
    message: str | None = None,
) -> WriteResultMoved:
    """Move or rename a file within a repository on a single branch."""

    m = _main()

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    effective_branch, normalized_from_path = _normalize_write_context(
        full_name, branch, from_path
    )
    if normalized_from_path is None:
        raise ValueError("from_path must not be empty after normalization")
    _, normalized_to_path = _normalize_write_context(full_name, effective_branch, to_path)
    if normalized_to_path is None:
        raise ValueError("to_path must not be empty after normalization")

    if normalized_from_path == normalized_to_path:
        raise ValueError("from_path and to_path must be different")

    source = await m._decode_github_content(full_name, normalized_from_path, effective_branch)
    source_text = require_text(
        source,
        error_message="Source file contents missing or undecodable",
    )

    commit_message = message or f"Move {normalized_from_path} to {normalized_to_path}"

    write_result = await apply_text_update_and_commit(
        full_name=full_name,
        path=normalized_to_path,
        updated_content=source_text,
        branch=effective_branch,
        message=commit_message + " (add new path)",
    )

    delete_body = {
        "message": commit_message + " (remove old path)",
        "branch": effective_branch,
    }
    try:
        delete_body["sha"] = await m._resolve_file_sha(
            full_name, normalized_from_path, effective_branch
        )
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        if getattr(exc, "status_code", None) == 404:
            delete_result = {"status": "noop", "reason": "source path missing"}
        else:
            raise
    else:
        delete_result = await m._github_request(
            "DELETE",
            f"/repos/{full_name}/contents/{normalized_from_path}",
            json=delete_body,
        )


    # Render-log friendly move/delete summaries.
    try:
        config.TOOLS_LOGGER.chat(
            "Moved %s -> %s",
            normalized_from_path,
            normalized_to_path,
            extra={
                "repo": full_name,
                "from_path": normalized_from_path,
                "to_path": normalized_to_path,
                "event": "write_move",
            },
        )

        # If we actually deleted the old path, also show the deletion diff.
        if isinstance(delete_result, dict) and delete_result.get("status") != "noop":
            delete_diff = build_unified_diff(
                source_text,
                "",
                fromfile=f"a/{normalized_from_path}",
                tofile=f"b/{normalized_from_path}",
            )
            log_write_diff(
                "Removed",
                full_name=full_name,
                path=normalized_from_path,
                diff_text=delete_diff,
                detail_suffix=" (deleted)",
            )
    except Exception:
        config.TOOLS_LOGGER.debug(
            "Move diff logging failed",
            exc_info=True,
            extra={
                "repo": full_name,
                "from_path": normalized_from_path,
                "to_path": normalized_to_path,
            },
        )

    return {
        "status": "moved",
        "full_name": full_name,
        "branch": effective_branch,
        "from_path": normalized_from_path,
        "to_path": normalized_to_path,
        "write_result": write_result,
        "delete_result": delete_result,
    }

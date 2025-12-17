from __future__ import annotations

from typing import Any, Dict, Optional

import github_mcp.config as config
from github_mcp.diff_utils import (
    build_unified_diff,
    colorize_unified_diff,
    diff_stats,
    truncate_diff,
)

from ._main import _main


async def create_file(
    full_name: str,
    path: str,
    content: str,
    *,
    branch: str = "main",
    message: Optional[str] = None,
    return_diff: bool = False,
) -> Dict[str, Any]:
    """Create a new text file in a repository after normalizing path and branch."""

    m = _main()
    _ = return_diff  # noqa: F841

    effective_branch = m._effective_ref_for_repo(full_name, branch)
    normalized_path = m._normalize_repo_path(path)


    m._ensure_write_allowed(
        "create_file %s %s" % (full_name, normalized_path),
        target_ref=effective_branch,
    )

    # Ensure the file does not already exist.
    try:
        await m._decode_github_content(full_name, normalized_path, effective_branch)
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        msg = str(exc)
        if "404" in msg:
            sha_before: Optional[str] = None
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
    json_blob = verified.get("json")
    sha_after: Optional[str]
    if isinstance(json_blob, dict) and isinstance(json_blob.get("sha"), str):
        sha_after = json_blob["sha"]
    else:
        sha_value = verified.get("sha")
        sha_after = sha_value if isinstance(sha_value, str) else None

    # Render-log friendly diff logging (colored additions/removals).
    full_diff = build_unified_diff(
        "",
        content,
        fromfile=f"a/{normalized_path}",
        tofile=f"b/{normalized_path}",
    )
    stats = diff_stats(full_diff)

    try:
        config.TOOLS_LOGGER.chat(
            "Created %s (+%s -%s)",
            normalized_path,
            stats.added,
            stats.removed,
            extra={"repo": full_name, "path": normalized_path, "event": "write_diff_summary"},
        )

        if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and full_diff.strip():
            truncated = truncate_diff(
                full_diff,
                max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
            )
            colored = colorize_unified_diff(truncated)
            config.TOOLS_LOGGER.detailed(
                "Diff for %s\n%s",
                normalized_path,
                colored,
                extra={"repo": full_name, "path": normalized_path, "event": "write_diff"},
            )
    except Exception:
        # Diff logging should never break the tool.
        pass

    diff_text: Optional[str] = None
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
    message: Optional[str] = None,
    return_diff: bool = False,
) -> Dict[str, Any]:
    """Apply a text update to a single file on a branch, then verify it."""

    m = _main()

    effective_branch = m._effective_ref_for_repo(full_name, branch)
    normalized_path = m._normalize_repo_path(path)


    m._ensure_write_allowed(
        "apply_text_update_and_commit %s %s" % (full_name, normalized_path),
        target_ref=effective_branch,
    )

    is_new_file = False
    old_text: str | None = None

    def _extract_sha(decoded: Dict[str, Any]) -> Optional[str]:
        if not isinstance(decoded, dict):
            return None
        json_blob = decoded.get("json")
        if isinstance(json_blob, dict) and isinstance(json_blob.get("sha"), str):
            return json_blob.get("sha")
        sha_value = decoded.get("sha")
        return sha_value if isinstance(sha_value, str) else None

    try:
        decoded = await m._decode_github_content(full_name, normalized_path, effective_branch)
        _old_text = decoded.get("text")
        if not isinstance(_old_text, str):
            raise m.GitHubAPIError("Decoded content is not text")
        old_text = _old_text  # type: ignore[attr-defined]
        sha_before = _extract_sha(decoded)
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        msg = str(exc)
        if "404" in msg:
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
    sha_after = _extract_sha(verified)

    # Render-log friendly diff logging (colored additions/removals).
    before = old_text or ""
    after = updated_content
    full_diff = build_unified_diff(
        before,
        after,
        fromfile=f"a/{normalized_path}",
        tofile=f"b/{normalized_path}",
    )
    stats = diff_stats(full_diff)

    # Minimal progress note (CHAT) + detailed colored diff when enabled.
    try:
        config.TOOLS_LOGGER.chat(
            "Committed %s (+%s -%s)",
            normalized_path,
            stats.added,
            stats.removed,
            extra={"repo": full_name, "path": normalized_path, "event": "write_diff_summary"},
        )

        if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and full_diff.strip():
            truncated = truncate_diff(
                full_diff,
                max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
            )
            colored = colorize_unified_diff(truncated)
            config.TOOLS_LOGGER.detailed(
                "Diff for %s:\n%s",
                normalized_path,
                colored,
                extra={"repo": full_name, "path": normalized_path, "event": "write_diff"},
            )
    except Exception:
        # Diff logging should never break the tool.
        pass

    diff_text: Optional[str] = None
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
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Move or rename a file within a repository on a single branch."""

    m = _main()

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    effective_branch = m._effective_ref_for_repo(full_name, branch)

    m._ensure_write_allowed(
        f"move_file from {from_path} to {to_path} in {full_name}@{effective_branch}",
        target_ref=effective_branch,
    )

    from_path = m._normalize_repo_path(from_path)
    to_path = m._normalize_repo_path(to_path)

    if from_path == to_path:
        raise ValueError("from_path and to_path must be different")

    source = await m._decode_github_content(full_name, from_path, effective_branch)
    source_text = source.get("text")
    if source_text is None:
        raise m.GitHubAPIError("Source file contents missing or undecodable")  # type: ignore[attr-defined]

    commit_message = message or f"Move {from_path} to {to_path}"

    write_result = await m.apply_text_update_and_commit(
        full_name=full_name,
        path=to_path,
        updated_content=source_text,
        branch=effective_branch,
        message=commit_message + " (add new path)",
    )

    delete_body = {
        "message": commit_message + " (remove old path)",
        "branch": effective_branch,
    }
    try:
        delete_body["sha"] = await m._resolve_file_sha(full_name, from_path, effective_branch)
    except m.GitHubAPIError as exc:  # type: ignore[attr-defined]
        msg = str(exc)
        if "404" in msg:
            delete_result = {"status": "noop", "reason": "source path missing"}
        else:
            raise
    else:
        delete_result = await m._github_request(
            "DELETE",
            f"/repos/{full_name}/contents/{from_path}",
            json=delete_body,
        )


    # Render-log friendly move/delete summaries.
    try:
        config.TOOLS_LOGGER.chat(
            "Moved %s -> %s",
            from_path,
            to_path,
            extra={"repo": full_name, "from_path": from_path, "to_path": to_path, "event": "write_move"},
        )

        # If we actually deleted the old path, also show the deletion diff.
        if isinstance(delete_result, dict) and delete_result.get("status") != "noop":
            delete_diff = build_unified_diff(
                source_text,
                "",
                fromfile=f"a/{from_path}",
                tofile=f"b/{from_path}",
            )
            stats = diff_stats(delete_diff)
            config.TOOLS_LOGGER.chat(
                "Removed %s (+%s -%s)",
                from_path,
                stats.added,
                stats.removed,
                extra={"repo": full_name, "path": from_path, "event": "write_diff_summary"},
            )
            if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and delete_diff.strip():
                truncated = truncate_diff(
                    delete_diff,
                    max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                    max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
                )
                colored = colorize_unified_diff(truncated)
                config.TOOLS_LOGGER.detailed(
                    "Diff for %s (deleted)\n%s",
                    from_path,
                    colored,
                    extra={"repo": full_name, "path": from_path, "event": "write_diff"},
                )
    except Exception:
        pass

    return {
        "status": "moved",
        "full_name": full_name,
        "branch": effective_branch,
        "from_path": from_path,
        "to_path": to_path,
        "write_result": write_result,
        "delete_result": delete_result,
    }

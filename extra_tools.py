from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Protocol

from github_mcp.config import (
    GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_CHARS,
    GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_LINES,
    GET_FILE_WITH_LINE_NUMBERS_HARD_MAX_LINES,
)
from main import (
    _decode_github_content,
    _effective_ref_for_repo,
    _ensure_write_allowed,
    _github_request,
    _resolve_file_sha,
    _workspace_path,
)


class ToolDecorator(Protocol):
    """Minimal protocol for the `mcp_tool` decorator supplied by main.py."""

    def __call__(
        self,
        *,
        write_action: bool = False,
        **tool_kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def ping_extensions() -> str:
    """Simple ping used for diagnostics."""

    return "pong from extra_tools.py"


async def get_file_slice(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int = 1,
    max_lines: int = GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_LINES,
) -> Dict[str, Any]:
    """Fetch a line-range slice of a text file."""

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)

    decoded = await _decode_github_content(full_name, path, effective_ref)
    text = decoded.get("text", "")
    all_lines = str(text).splitlines(keepends=False)
    total_lines = len(all_lines)

    if total_lines == 0:
        return {
            "full_name": full_name,
            "path": path,
            "ref": effective_ref,
            "start_line": 1,
            "end_line": 0,
            "max_lines": max_lines,
            "total_lines": 0,
            "has_more_above": False,
            "has_more_below": False,
            "lines": [],
        }

    start_idx = min(max(start_line - 1, 0), total_lines - 1)
    end_idx = min(start_idx + max_lines, total_lines)

    slice_lines = [{"line": i + 1, "text": all_lines[i]} for i in range(start_idx, end_idx)]

    return {
        "full_name": full_name,
        "path": path,
        "ref": effective_ref,
        "start_line": start_idx + 1,
        "end_line": end_idx,
        "max_lines": max_lines,
        "total_lines": total_lines,
        "has_more_above": start_idx > 0,
        "has_more_below": end_idx < total_lines,
        "lines": slice_lines,
    }


async def get_file_with_line_numbers(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int = 1,
    max_lines: int = GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_LINES,
    max_chars: int = GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Return a line-numbered string and structured lines for a file slice.

    This tool is user-facing and must stay bounded. By default it returns up to
    200 lines (or less if max_chars is reached). Override max_lines/max_chars
    explicitly when you truly need more context.
    """

    hard_max = GET_FILE_WITH_LINE_NUMBERS_HARD_MAX_LINES
    if hard_max > 0 and max_lines > hard_max:
        max_lines = hard_max
    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)

    decoded = await _decode_github_content(full_name, path, effective_ref)
    text = decoded.get("text", "")
    all_lines = str(text).splitlines(keepends=False)
    total_lines = len(all_lines)

    if total_lines == 0:
        return {
            "full_name": full_name,
            "path": path,
            "ref": effective_ref,
            "start_line": 1,
            "end_line": 0,
            "max_lines": max_lines,
            "total_lines": 0,
            "has_more_above": False,
            "has_more_below": False,
            "lines": [],
            "numbered_text": "",
            "truncated": False,
        }
    # Hard cap response size to avoid hangs/network errors (tunable via env defaults).
    effective_max_chars = int(max_chars)
    if effective_max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    start_idx = min(max(start_line - 1, 0), total_lines - 1)
    end_idx_requested = min(start_idx + max_lines, total_lines)

    width = len(str(total_lines)) if total_lines > 0 else 1
    slice_lines: list[dict[str, Any]] = []
    numbered_lines: list[str] = []
    char_count = 0
    truncated = False

    for i in range(start_idx, end_idx_requested):
        entry = {"line": i + 1, "text": all_lines[i]}
        rendered = f"{entry['line']:>{width}}| {entry['text']}"
        # Account for newline separators too.
        additional = len(rendered) + (1 if numbered_lines else 0)
        if numbered_lines and (char_count + additional) > effective_max_chars:
            truncated = True
            break
        slice_lines.append(entry)
        numbered_lines.append(rendered)
        char_count += additional

    end_idx_actual = start_idx + len(slice_lines)
    if end_idx_actual < end_idx_requested:
        truncated = True

    numbered_text = "\n".join(numbered_lines)
    if truncated and numbered_text:
        numbered_text = numbered_text + "\n… (truncated)"

    return {
        "full_name": full_name,
        "path": path,
        "ref": effective_ref,
        "start_line": start_idx + 1,
        "end_line": end_idx_actual,
        "max_lines": max_lines,
        "total_lines": total_lines,
        "has_more_above": start_idx > 0,
        "has_more_below": end_idx_actual < total_lines,
        "lines": slice_lines,
        "numbered_text": numbered_text,
        "truncated": truncated,
        "max_chars": effective_max_chars,
        "returned_chars": len(numbered_text),
    }


async def open_file_context(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int | None = None,
    max_lines: int = GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_LINES,
) -> Dict[str, Any]:
    """Fetch a bounded file slice with explicit line numbers and content list."""

    normalized_start_line = 1 if start_line is None else start_line
    if normalized_start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    slice_result = await get_file_slice(
        full_name=full_name,
        path=path,
        ref=ref,
        start_line=normalized_start_line,
        max_lines=max_lines,
    )

    total_lines = slice_result.get("total_lines")
    should_expand_small_file = (
        normalized_start_line == 1
        and isinstance(total_lines, int)
        and total_lines > 0
        and total_lines <= 120
        and slice_result.get("end_line", 0) < total_lines
    )

    if should_expand_small_file:
        slice_result = await get_file_slice(
            full_name=full_name,
            path=path,
            ref=ref,
            start_line=1,
            max_lines=int(total_lines),
        )

    content_entries = [
        {"line": entry["line"], "text": entry["text"]} for entry in slice_result.get("lines", [])
    ]

    response: Dict[str, Any] = {
        "full_name": slice_result.get("full_name", full_name),
        "path": slice_result.get("path", path),
        "ref": slice_result.get("ref", ref),
        "start_line": slice_result.get("start_line"),
        "end_line": slice_result.get("end_line"),
        "total_lines": slice_result.get("total_lines"),
        "content": content_entries,
        "has_more_above": slice_result.get("has_more_above", False),
        "has_more_below": slice_result.get("has_more_below", False),
    }

    if should_expand_small_file:
        response["note"] = "File is small; returning full content instead of only max_lines."

    return response


async def delete_file(
    full_name: str,
    path: str,
    message: str = "Delete file via MCP GitHub connector",
    branch: str = "main",
    if_missing: Literal["error", "noop"] = "error",
) -> Dict[str, Any]:
    """Delete a single file in a repository via the GitHub Contents API."""

    if if_missing not in ("error", "noop"):
        raise ValueError("if_missing must be 'error' or 'noop'")

    effective_branch = _effective_ref_for_repo(full_name, branch)
    _ensure_write_allowed(
        f"delete_file {full_name} {path}",
        target_ref=effective_branch,
    )

    sha = await _resolve_file_sha(full_name, path, effective_branch)
    if sha is None:
        if if_missing == "noop":
            return {
                "status": "noop",
                "full_name": full_name,
                "path": path,
                "branch": effective_branch,
            }
        raise FileNotFoundError(f"File not found: {path} on {effective_branch}")

    payload = {"message": message, "sha": sha, "branch": effective_branch}
    result = await _github_request(
        "DELETE",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
        expect_json=True,
    )

    return {
        "status": "deleted",
        "full_name": full_name,
        "path": path,
        "branch": effective_branch,
        "commit": result,
    }


async def update_file_from_workspace(
    full_name: str,
    workspace_path: str,
    target_path: str,
    branch: str,
    message: str,
) -> Dict[str, Any]:
    """Commit a workspace file to a target path in the repository."""

    effective_ref = _effective_ref_for_repo(full_name, branch)

    _ensure_write_allowed(
        f"update_file_from_workspace {full_name} {target_path}",
        target_ref=effective_ref,
    )

    workspace_root = _workspace_path(full_name, effective_ref)

    workspace_file = Path(workspace_root) / workspace_path
    if not workspace_file.is_file():
        raise FileNotFoundError(
            f"Workspace file {workspace_path!r} not found in {workspace_root!r}"
        )

    content_bytes = workspace_file.read_bytes()
    encoded = base64.b64encode(content_bytes).decode("ascii")

    sha = await _resolve_file_sha(full_name, target_path, effective_ref)

    payload: Dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": effective_ref,
    }
    if sha is not None:
        payload["sha"] = sha

    result = await _github_request(
        "PUT",
        f"/repos/{full_name}/contents/{target_path}",
        json_body=payload,
        expect_json=True,
    )

    return {
        "full_name": full_name,
        "branch": effective_ref,
        "workspace_path": workspace_path,
        "target_path": target_path,
        "commit": result,
    }


def register_extra_tools(mcp_tool: ToolDecorator) -> None:
    """Register optional extra tools on top of the core MCP toolset."""

    # meta / diagnostics
    mcp_tool(
        write_action=False,
        description="Ping the MCP server extensions surface.",
        tags=["meta", "diagnostics"],
    )(ping_extensions)  # type: ignore[arg-type]

    # read/context helpers
    mcp_tool(
        write_action=False,
        description="Return a citation-friendly slice of a file.",
        tags=["github", "read", "files", "context"],
    )(get_file_slice)  # type: ignore[arg-type]

    mcp_tool(
        write_action=False,
        description=("Render a compact, line-numbered view of a file to simplify manual edits."),
        tags=["github", "read", "files", "ergonomics"],
    )(get_file_with_line_numbers)  # type: ignore[arg-type]

    mcp_tool(
        write_action=False,
        description=(
            "Return a citation-friendly slice of a file with line numbers and content entries."
        ),
        tags=["github", "read", "files", "context"],
    )(open_file_context)  # type: ignore[arg-type]

    # write actions
    mcp_tool(
        write_action=True,
        description=(
            "Delete a file from a GitHub repository using the Contents API. "
            "Use ensure_branch if you want to delete on a dedicated branch."
        ),
        tags=["github", "write", "files", "delete"],
    )(delete_file)  # type: ignore[arg-type]

    mcp_tool(
        write_action=True,
        description=(
            "Update a single file in a GitHub repository from the persistent "
            "workspace checkout. Use terminal_command to edit the workspace file "
            "first, then call this tool to sync it back to the branch."
        ),
        tags=["github", "write", "files"],
    )(update_file_from_workspace)  # type: ignore[arg-type]

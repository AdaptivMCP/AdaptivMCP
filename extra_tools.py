from __future__ import annotations

import base64
import difflib
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, NotRequired, Optional, Protocol, TypedDict

from main import (
    GitHubAPIError,
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


class SectionReplacement(TypedDict):
    """Substring replacement used by update_file_sections_and_commit."""

    match_text: str
    replacement_text: str


class LineEditSection(TypedDict):
    """Line-based edit used by diff/edit helpers."""

    start_line: int
    end_line: int
    new_text: str
    expected_text: NotRequired[str]


def _render_visible_whitespace(line: str) -> str:
    """Render spaces/tabs with visible glyphs for human-oriented previews."""

    return line.replace(" ", "·").replace("\t", "→\t").rstrip("\n")


def _apply_line_sections(text: str, sections: List[LineEditSection]) -> Dict[str, Any]:
    """Apply normalized line-based sections to text and return metadata."""

    if sections is None:
        raise ValueError("sections must be provided")

    original_lines = text.splitlines(keepends=True)
    total_lines = len(original_lines)

    normalized_sections: List[LineEditSection] = sorted(
        sections, key=lambda s: int(s.get("start_line", 0))  # type: ignore[arg-type]
    )

    prev_end = 0
    max_start = total_lines + 1

    for section in normalized_sections:
        try:
            start_line = int(section["start_line"])
            end_line = int(section["end_line"])
        except KeyError as exc:
            raise ValueError("Each section must have 'start_line' and 'end_line'") from exc

        if "new_text" not in section:
            raise ValueError("Each section must include new_text (can be empty)")
        if section.get("new_text") is None:
            raise ValueError("new_text must not be None; use '' for deletions")

        if start_line < 1:
            raise ValueError("start_line must be >= 1")
        if start_line > max_start:
            raise ValueError(
                f"start_line {start_line} is beyond end of file ({total_lines} lines)"
            )

        # Allow end_line == start_line - 1 to represent a pure insertion.
        if end_line < start_line - 1:
            raise ValueError("end_line must be >= start_line - 1")

        # The only valid case where end_line can exceed total_lines is when
        # both start and end point one past the end, which represents an
        # append-only insertion.
        if end_line > total_lines and not (end_line == start_line == max_start):
            raise ValueError(f"end_line {end_line} is greater than total_lines {total_lines}")
        if start_line <= prev_end:
            raise ValueError("sections must not overlap or go backwards")
        prev_end = end_line

        expected_text = section.get("expected_text")
        if expected_text is not None:
            existing_slice = "".join(original_lines[start_line - 1 : end_line])
            if existing_slice != expected_text:
                raise ValueError(
                    "expected_text does not match the current file content for "
                    f"section starting at line {start_line}"
                )

    updated_lines: List[str] = []
    cursor = 1

    for section in normalized_sections:
        start_line = int(section["start_line"])
        end_line = int(section["end_line"])
        new_text = section.get("new_text", "")

        # Copy unchanged lines before the section.
        if cursor <= start_line - 1 and total_lines > 0:
            updated_lines.extend(original_lines[cursor - 1 : min(start_line - 1, total_lines)])

        # Apply replacement text (may be empty for pure deletion).
        if new_text:
            replacement_text = new_text

            # If we're appending to a file that currently lacks a trailing
            # newline, make sure the insertion starts on a new line.
            if (
                start_line >= max_start
                and total_lines > 0
                and updated_lines
                and not updated_lines[-1].endswith("\n")
                and not replacement_text.startswith("\n")
            ):
                replacement_text = "\n" + replacement_text

            replacement_lines = replacement_text.splitlines(keepends=True)
            updated_lines.extend(replacement_lines)

        # Move cursor past the replaced range; for insertion (end_line == start_line - 1)
        # this leaves cursor unchanged relative to original_lines.
        cursor = max(cursor, end_line + 1)

    # Copy the tail of the file.
    if total_lines > 0 and cursor <= total_lines:
        updated_lines.extend(original_lines[cursor - 1 :])

    updated_text = "".join(updated_lines)

    return {
        "updated_text": updated_text,
        "original_lines": original_lines,
        "total_lines": total_lines,
        "normalized_sections": normalized_sections,
    }


def _build_unified_diff_from_strings(
    original: str,
    updated: str,
    path: str = "file.txt",
    context_lines: int = 3,
    show_whitespace: bool = False,
) -> Dict[str, Any]:
    """Build a unified diff between two text buffers."""

    if context_lines < 0:
        raise ValueError("context_lines must be >= 0")

    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)

    fromfile = f"a/{path}"
    tofile = f"b/{path}"

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            updated_lines,
            fromfile=fromfile,
            tofile=tofile,
            n=context_lines,
        )
    )
    patch = "".join(diff_lines)

    result: Dict[str, Any] = {
        "path": path,
        "patch": patch,
        "context_lines": context_lines,
    }

    if show_whitespace:
        preview_lines: List[str] = []
        for line in diff_lines:
            if (
                line.startswith(("+", "-", " "))
                and not line.startswith("+++")
                and not line.startswith("---")
            ):
                prefix, payload = line[0], line[1:]
                preview_lines.append(prefix + _render_visible_whitespace(payload) + "\n")
            else:
                preview_lines.append(line)
        result["preview"] = "".join(preview_lines)

    return result


async def build_section_based_diff(
    full_name: str,
    path: str,
    sections: List[LineEditSection],
    ref: str = "main",
    context_lines: int = 3,
    show_whitespace: bool = False,
) -> Dict[str, Any]:
    """Build a unified diff from line-based sections."""

    if context_lines < 0:
        raise ValueError("context_lines must be >= 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)
    decoded = await _decode_github_content(full_name, path, effective_ref)
    text = decoded.get("text", "")

    applied = _apply_line_sections(text, sections)
    updated_text = applied["updated_text"]
    normalized_sections = applied["normalized_sections"]

    diff_result = _build_unified_diff_from_strings(
        text,
        updated_text,
        path=path,
        context_lines=context_lines,
        show_whitespace=show_whitespace,
    )
    diff_result["full_name"] = full_name
    diff_result["ref"] = effective_ref
    diff_result["applied_sections"] = normalized_sections
    return diff_result


async def get_file_slice(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int = 1,
    max_lines: int = 200,
) -> Dict[str, Any]:
    """Fetch a line-range slice of a text file."""

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)

    decoded = await _decode_github_content(full_name, path, effective_ref)
    text = decoded.get("text", "")
    all_lines = text.splitlines(keepends=False)
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

    has_more_above = start_idx > 0
    has_more_below = end_idx < total_lines

    return {
        "full_name": full_name,
        "path": path,
        "ref": effective_ref,
        "start_line": start_idx + 1,
        "end_line": end_idx,
        "max_lines": max_lines,
        "total_lines": total_lines,
        "has_more_above": has_more_above,
        "has_more_below": has_more_below,
        "lines": slice_lines,
    }


async def get_file_with_line_numbers(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int = 1,
    max_lines: int = 5000,
) -> Dict[str, Any]:
    """Return a line-numbered string and structured lines for a file slice.

    AI Assistants are not allowed to change default max_lines.
    """

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)

    decoded = await _decode_github_content(full_name, path, effective_ref)
    text = decoded.get("text", "")
    all_lines = text.splitlines(keepends=False)
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
        }

    start_idx = min(max(start_line - 1, 0), total_lines - 1)
    end_idx = min(start_idx + max_lines, total_lines)

    slice_lines = [{"line": i + 1, "text": all_lines[i]} for i in range(start_idx, end_idx)]

    width = len(str(total_lines)) if total_lines > 0 else 1
    numbered_text = "\n".join(
        f"{entry['line']:>{width}}| {entry['text']}" for entry in slice_lines
    )

    has_more_above = start_idx > 0
    has_more_below = end_idx < total_lines

    return {
        "full_name": full_name,
        "path": path,
        "ref": effective_ref,
        "start_line": start_idx + 1,
        "end_line": end_idx,
        "max_lines": max_lines,
        "total_lines": total_lines,
        "has_more_above": has_more_above,
        "has_more_below": has_more_below,
        "lines": slice_lines,
        "numbered_text": numbered_text,
    }


async def open_file_context(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int | None = None,
    max_lines: int = 200,
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
            max_lines=total_lines,
        )

    content_entries = [
        {"line": entry["line"], "text": entry["text"]}
        for entry in slice_result.get("lines", [])
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


async def update_file_sections_and_commit(
    full_name: str,
    path: str,
    branch: str = "main",
    message: str = "Update file via sections",
    sections: Optional[List[SectionReplacement]] = None,
) -> Dict[str, Any]:
    """Apply substring-based replacements to a file and commit the result."""

    if not sections:
        raise ValueError("sections must be a non-empty list")

    effective_branch = _effective_ref_for_repo(full_name, branch)
    decoded = await _decode_github_content(full_name, path, effective_branch)
    current_text = decoded.get("text")
    if not isinstance(current_text, str):
        raise GitHubAPIError("Decoded content is not text")

    updated_text = current_text
    for section in sections:
        match_text = section.get("match_text")
        replacement_text = section.get("replacement_text")
        if not match_text:
            raise ValueError("Each section must include match_text")
        if replacement_text is None:
            raise ValueError("Each section must include replacement_text")
        if match_text not in updated_text:
            raise ValueError(f"match_text not found in {path}")
        updated_text = updated_text.replace(match_text, replacement_text, 1)

    if updated_text == current_text:
        return {
            "status": "no-op",
            "full_name": full_name,
            "path": path,
            "branch": effective_branch,
        }

    from main import apply_text_update_and_commit

    commit_result = await apply_text_update_and_commit(
        full_name=full_name,
        path=path,
        updated_content=updated_text,
        branch=effective_branch,
        message=message,
        return_diff=True,
        context_lines=3,
    )

    return {
        "status": "committed",
        "full_name": full_name,
        "path": path,
        "branch": effective_branch,
        "message": message,
        "commit": commit_result.get("commit"),
        "verification": commit_result.get("verification"),
        "diff": commit_result.get("diff"),
    }


async def apply_line_edits_and_commit(
    full_name: str,
    path: str,
    sections: List[LineEditSection],
    branch: str = "main",
    message: str = "Apply line edits",
    include_diff: bool = False,
    context_lines: int = 3,
) -> Dict[str, Any]:
    """Apply line-based edits and commit the result."""

    if context_lines < 0:
        raise ValueError("context_lines must be >= 0")

    effective_branch = _effective_ref_for_repo(full_name, branch)
    decoded = await _decode_github_content(full_name, path, effective_branch)
    current_text = decoded.get("text", "")

    applied = _apply_line_sections(current_text, sections)
    updated_text = applied["updated_text"]
    normalized_sections = applied["normalized_sections"]

    if updated_text == current_text:
        return {
            "status": "no-op",
            "reason": "no_changes",
            "full_name": full_name,
            "path": path,
            "branch": effective_branch,
            "applied_sections": normalized_sections,
        }

    from main import apply_text_update_and_commit

    commit_result = await apply_text_update_and_commit(
        full_name=full_name,
        path=path,
        updated_content=updated_text,
        branch=effective_branch,
        message=message,
        return_diff=include_diff,
        context_lines=context_lines,
    )

    commit_result["applied_sections"] = normalized_sections
    commit_result["context_lines"] = context_lines
    return commit_result


def ping_extensions() -> str:
    """Simple ping used for diagnostics."""

    return "pong from extra_tools.py"


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
                "status": "skipped",
                "reason": "file_not_found",
                "full_name": full_name,
                "path": path,
                "branch": effective_branch,
                "message": (
                    f"File {path!r} not found in {full_name}@{effective_branch}; "
                    "nothing to delete."
                ),
            }
        raise GitHubAPIError(
            f"File {path!r} not found in {full_name}@{effective_branch}; cannot delete."
        )

    payload = {
        "message": message,
        "sha": sha,
        "branch": effective_branch,
    }

    result = await _github_request(
        "DELETE",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
        expect_json=True,
    )

    return {
        "status": "deleted",
        "full_name": full_name,
        "branch": effective_branch,
        "commit": result,
    }


async def update_file_from_workspace(
    full_name: str,
    branch: str,
    workspace_path: str,
    target_path: str,
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
        description=(
            "Render a compact, line-numbered view of a file to simplify manual edits."
        ),
        tags=["github", "read", "files", "ergonomics"],
    )(get_file_with_line_numbers)  # type: ignore[arg-type]

    mcp_tool(
        write_action=False,
        description=(
            "Return a citation-friendly slice of a file with line numbers and content entries."
        ),
        tags=["github", "read", "files", "context"],
    )(open_file_context)  # type: ignore[arg-type]

    # diff/edit helpers
    mcp_tool(
        write_action=False,
        description="Build a unified diff from line-based sections.",
        tags=["github", "read", "diff"],
    )(build_section_based_diff)  # type: ignore[arg-type]

    mcp_tool(
        write_action=True,
        description="Apply line-based edits to a file and commit the result.",
        tags=["github", "write", "files", "diff"],
    )(apply_line_edits_and_commit)  # type: ignore[arg-type]

    mcp_tool(
        write_action=True,
        description="Apply substring-based replacements to a file and commit the result.",
        tags=["github", "write", "files"],
    )(update_file_sections_and_commit)  # type: ignore[arg-type]

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
            "workspace checkout. Use run_command to edit the workspace file "
            "first, then call this tool to sync it back to the branch."
        ),
        tags=["github", "write", "files"],
    )(update_file_from_workspace)  # type: ignore[arg-type]

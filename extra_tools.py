from __future__ import annotations

import difflib
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
    """Protocol describing the `mcp_tool` decorator from `main.py`.

    This stays intentionally minimal so that changes to the real decorator
    signature are less likely to break this extension surface.
    """

    def __call__(
        self,
        *,
        write_action: bool = False,
        **tool_kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


class SectionReplacement(TypedDict):
    """Simple substring replacement used by update_file_sections_and_commit."""

    match_text: str
    replacement_text: str


class LineEditSection(TypedDict):
    """Line-based edit used by build_section_based_diff/apply_line_edits_and_commit."""

    start_line: int
    end_line: int
    new_text: str
    expected_text: NotRequired[str]


def _render_visible_whitespace(line: str) -> str:
    """Render spaces and tabs with visible glyphs for debugging diffs.

    This is only used for human-oriented previews; the actual `patch` returned
    by build_unified_diff remains a valid unified diff suitable for
    apply_patch_and_commit.
    """
    return (
        line.replace(" ", "·")
        .replace("\t", "→\t")
        .rstrip("\n")  # avoid duplicating newlines in the preview
    )


def register_extra_tools(mcp_tool: ToolDecorator) -> None:
    """Register optional extra tools on top of the core MCP toolset.

    This function is discovered dynamically by `main.py` (if present) and
    receives the `mcp_tool` decorator so you can define additional tools
    without having to modify the core server implementation.
    """

    @mcp_tool(
        write_action=False,
        description="Ping the MCP server extensions surface. Useful for diagnostics.",
        tags=["meta", "diagnostics"],
    )
    def ping_extensions() -> str:
        """Return a simple ping response from extra_tools."""
        return "pong from extra_tools.py"

    @mcp_tool(
        write_action=True,
        description=(
            "Delete a file from a GitHub repository using the Contents API."
            " Use ensure_branch if you want to delete on a dedicated branch."
        ),
        tags=["github", "write", "files", "delete"],
    )
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

        # Enforce write gating using the same helper as core tools.
        _ensure_write_allowed(
            f"delete_file {full_name} {path}",
            target_ref=effective_branch,
        )

        # Resolve the current file SHA so we can issue a DELETE via the
        # Contents API.
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

    @mcp_tool(
        write_action=True,
        description=(
            "Update a single file in a GitHub repository from the persistent "
            "workspace checkout. Use run_command to edit the workspace file "
            "first, then call this tool to sync it back to the branch."
        ),
        tags=["github", "write", "files"],
    )
    async def update_file_from_workspace(
        full_name: str,
        branch: str,
        workspace_path: str,
        target_path: str,
        message: str,
    ) -> Dict[str, Any]:
        """Commit a workspace file to a target path in the repository."""

        effective_ref = _effective_ref_for_repo(full_name, branch)

        # Respect the same write gating semantics as core tools.
        _ensure_write_allowed(
            f"update_file_from_workspace {full_name} {target_path}",
            target_ref=effective_ref,
        )

        workspace_root = _workspace_path(full_name, effective_ref)

        import base64
        from pathlib import Path as _Path

        workspace_file = _Path(workspace_root) / workspace_path

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

    @mcp_tool(
        write_action=True,
        description=(
            "Update a file by applying simple section-based replacements and "
            "commit the result to a branch."
        ),
        tags=["editing", "diff", "commit"],
    )
    async def update_file_sections_and_commit(
        full_name: str,
        path: str,
        branch: str = "main",
        message: str = "Update file via sections",
        sections: Optional[List[SectionReplacement]] = None,
    ) -> Dict[str, Any]:
        """Apply section-based string replacements to a file and commit the result."""

        if not sections:
            raise ValueError("sections must be a non-empty list")

        # Fetch current file content from GitHub using the shared decoder helper.
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
                "branch": branch,
            }

        # Commit via apply_text_update_and_commit helper.
        from main import apply_text_update_and_commit

        commit_result = await apply_text_update_and_commit(
            full_name=full_name,
            path=path,
            updated_content=updated_text,
            branch=branch,
            message=message,
            return_diff=True,
            context_lines=3,
        )

        return {
            "status": "committed",
            "full_name": full_name,
            "path": path,
            "branch": branch,
            "message": message,
            "commit": commit_result.get("commit"),
            "verification": commit_result.get("verification"),
            "diff": commit_result.get("diff"),
        }

    def _apply_line_sections(
        text: str,
        sections: Optional[List[LineEditSection]],
    ) -> Dict[str, Any]:
        """Validate and apply line-based sections to text, returning the new text."""

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
        """Internal helper to build a unified diff between two text buffers."""

        if context_lines < 0:
            raise ValueError("context_lines must be >= 0")

        # Split while preserving newlines so diffs stay line-accurate.
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
            preview_lines = []
            for line in diff_lines:
                # Keep diff prefixes (+/-/@@) but render whitespace in the payload
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

    @mcp_tool(
        write_action=False,
        description=(
            "Build a unified diff when you already have both the original and updated "
            "file content. Useful when fetching from GitHub is unnecessary. This tool "
            "refuses negative context sizes so patches stay well-formed."
        ),
        tags=["github", "read", "diff"],
    )
    def build_unified_diff_from_strings(
        original: str,
        updated: str,
        path: str = "file.txt",
        context_lines: int = 3,
        show_whitespace: bool = False,
    ) -> Dict[str, Any]:
        """Return a unified diff between original and updated content."""

        return _build_unified_diff_from_strings(
            original,
            updated,
            path=path,
            context_lines=context_lines,
            show_whitespace=show_whitespace,
        )

    @mcp_tool(
        write_action=False,
        description=(
            "Build a unified diff for a file by applying line-based section "
            "replacements. Useful for large files: you describe the sections "
            "to replace and then pass the resulting patch to apply_patch_and_commit."
        ),
        tags=["github", "read", "diff", "orchestration"],
    )
    async def build_section_based_diff(
        full_name: str,
        path: str,
        sections: List[LineEditSection],
        ref: str = "main",
        context_lines: int = 3,
        show_whitespace: bool = False,
    ) -> Dict[str, Any]:
        ...

        """Build a unified diff for a file from line-based section replacements."""
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

    @mcp_tool(
        write_action=False,
        description=(
            "Fetch a slice of a large text file by line range. "
            "Useful when the full file would be too large to return in a single tool call."
        ),
        tags=["github", "read", "files"],
    )
    async def get_file_slice(
        full_name: str,
        path: str,
        ref: str = "main",
        start_line: int = 1,
        max_lines: int = 200,
    ) -> Dict[str, Any]:
        """Return a line-range slice of a text file with basic metadata."""

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

    @mcp_tool(
        write_action=False,
        description=(
            "Return a citation-friendly slice of a file with line numbers. "
            "Wraps get_file_slice and normalizes the output for code review or referencing. "
            "Defaults to the repo's default branch and will expand very small files when starting at line 1 so you can see the whole file."
        ),
        tags=["github", "read", "files", "context"],
    )
    async def open_file_context(
        full_name: str,
        path: str,
        ref: str | None = None,
        start_line: int | None = None,
        max_lines: int = 200,
    ) -> Dict[str, Any]:
        """Fetch a bounded file slice with explicit line numbers."""

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
            total_lines is not None
            and total_lines <= 120
            and slice_result.get("start_line", 1) == 1
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

    @mcp_tool(
        write_action=False,
        description=(
            "Render a compact, line-numbered view of a file to simplify manual edits. "
            "Use start_line/max_lines to limit output size for very large files."
        ),
        tags=["github", "read", "files", "ergonomics"],
    )
    async def get_file_with_line_numbers(
        full_name: str,
        path: str,
        ref: str = "main",
        start_line: int = 1,
        max_lines: int = 5000,
    ) -> Dict[str, Any]:
        """Return a line-numbered string and structured lines for a file slice.
        AI Assistants are not allowed to change default max_lines."""

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

        width = len(str(total_lines))
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

    @mcp_tool(
        write_action=True,
        description=(
            "Apply minimal line-based edits to a file and commit them without "
            "sending the entire file content. Provide start/end lines and the "
            "replacement text for each section; the server fetches, patches, "
            "and commits on your behalf."
        ),
        tags=["github", "write", "files", "diff", "bandwidth"],
    )
    async def apply_line_edits_and_commit(
        full_name: str,
        path: str,
        sections: List[LineEditSection],
        branch: str = "main",
        message: str = "Apply line edits",
        include_diff: bool = False,
        context_lines: int = 3,
    ) -> Dict[str, Any]:
        """Apply line-based edits to a file, commit them, and optionally return a diff.

        Each section replaces the inclusive start/end range with ``new_text``; callers can
        also provide ``expected_text`` to fail fast if the current file content has drifted.
        """

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

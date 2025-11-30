from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol
import difflib

# Reuse GitHub helpers from the core server implementation. These are defined
# in main.py before extra_tools is imported, so this import is safe.
from main import (
    _github_request,
    _resolve_file_sha,
    GitHubAPIError,
    _decode_github_content,
    _effective_ref_for_repo,
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
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        ...


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
        return "pong from extra_tools.py"

    @mcp_tool(
        write_action=True,
        description=(
            "Delete a file from a GitHub repository using the Contents API."
            " Call ensure_branch first if you want to delete on a dedicated branch."
        ),
        tags=["github", "write", "files", "delete"],
    )
    async def delete_file(
        full_name: str,
        path: str,
        message: str = "Delete file via MCP GitHub connector",
        branch: str = "main",
        if_missing: str = "error",
    ) -> Dict[str, Any]:
        """Delete a single file in a repository using the GitHub Contents API.

        Args:
            full_name: "owner/repo" string.
            path: Path to the file in the repository.
            message: Commit message for the delete.
            branch: Branch to delete from (default "main").
            if_missing: Behaviour when the file does not exist:
                - "error" (default): raise a GitHubAPIError.
                - "noop": return a "skipped" result instead of failing.

        Returns:
            A JSON-like dict including the API response from GitHub.
        """

        if if_missing not in ("error", "noop"):
            raise ValueError("if_missing must be 'error' or 'noop'")

        effective_branch = _effective_ref_for_repo(full_name, branch)

        # Resolve the current file SHA so we can issue a DELETE via the
        # Contents API. We piggyback on the existing _resolve_file_sha helper
        # rather than re-implementing the logic here.
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
                        f"File {path!r} not found in {full_name}@{effective_branch}; nothing to delete."
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
                    preview_lines.append(
                        prefix + _render_visible_whitespace(payload) + "\n"
                    )
                else:
                    preview_lines.append(line)
            result["preview"] = "".join(preview_lines)

        return result

    @mcp_tool(
        write_action=False,
        description=(
            "Build a unified diff when you already have both the original and updated "
            "file content. Useful for patch-first flows where fetching from GitHub "
            "is unnecessary. This tool refuses negative context sizes so patches "
            "stay well-formed."
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
        sections: list[Dict[str, Any]],
        ref: str = "main",
        context_lines: int = 3,
        show_whitespace: bool = False,
    ) -> Dict[str, Any]:
        """
        Build a unified diff for a file from line-based section replacements.

        The tool refuses to run without explicit sections and validates them for
        ordering, overlap, and bounds before constructing a patch. Invalid
        ranges raise ``ValueError`` so assistants can surface the refusal mode
        cleanly.

        Args:
            full_name:
                "owner/repo" string.
            path:
                Path to the file in the repository.
            sections:
                List of sections, each of which must be a dict with:
                  - "start_line": 1-based inclusive start line.
                  - "end_line": 1-based inclusive end line
                    (may be equal to start_line - 1 to represent an insertion).
                  - "new_text": replacement text for that range.
            ref:
                Git ref (branch, tag, or SHA). Defaults to "main".
            context_lines:
                Number of context lines in the diff (default 3). Negative values
                are rejected.
            show_whitespace:
                Whether to include a human-oriented preview with visible
                whitespace markers, like build_unified_diff.

        Returns:
            A dict containing at least:
              - patch: unified diff as a string.
              - path: the file path.
              - context_lines: the context size used.
              - full_name: repo name.
              - ref: effective ref used for the lookup.
              - preview (optional): human-oriented diff if show_whitespace=True.
        """
        if sections is None:
            raise ValueError("sections must be provided")
        if context_lines < 0:
            raise ValueError("context_lines must be >= 0")

        effective_ref = _effective_ref_for_repo(full_name, ref)
        decoded = await _decode_github_content(full_name, path, effective_ref)
        text = decoded.get("text", "")
        original_lines = text.splitlines(keepends=True)
        total_lines = len(original_lines)

        # Normalize and validate sections.
        normalized_sections: list[Dict[str, Any]] = sorted(
            sections, key=lambda s: int(s.get("start_line", 0))
        )

        prev_end = 0
        for section in normalized_sections:
            try:
                start_line = int(section["start_line"])
                end_line = int(section["end_line"])
            except KeyError as exc:
                raise ValueError(
                    "Each section must have 'start_line' and 'end_line'"
                ) from exc

            if start_line < 1:
                raise ValueError("start_line must be >= 1")
            # Allow end_line == start_line - 1 to represent a pure insertion.
            if end_line < start_line - 1:
                raise ValueError("end_line must be >= start_line - 1")
            if total_lines > 0 and end_line > total_lines:
                raise ValueError(
                    f"end_line {end_line} is greater than total_lines {total_lines}"
                )
            if start_line <= prev_end:
                raise ValueError("sections must not overlap or go backwards")
            prev_end = end_line

        updated_lines: list[str] = []
        cursor = 1

        for section in normalized_sections:
            start_line = int(section["start_line"])
            end_line = int(section["end_line"])
            new_text = section.get("new_text", "")

            # Copy unchanged lines before the section.
            if cursor <= start_line - 1 and total_lines > 0:
                updated_lines.extend(
                    original_lines[cursor - 1 : min(start_line - 1, total_lines)]
                )

            # Apply replacement text (may be empty for pure deletion).
            if new_text:
                replacement_lines = new_text.splitlines(keepends=True)
                updated_lines.extend(replacement_lines)

            # Move cursor past the replaced range; for insertion (end_line == start_line - 1)
            # this leaves cursor unchanged relative to original_lines.
            cursor = max(cursor, end_line + 1)

        # Copy the tail of the file.
        if total_lines > 0 and cursor <= total_lines:
            updated_lines.extend(original_lines[cursor - 1 :])

        updated_text = "".join(updated_lines)

        diff_result = _build_unified_diff_from_strings(
            text,
            updated_text,
            path=path,
            context_lines=context_lines,
            show_whitespace=show_whitespace,
        )
        diff_result["full_name"] = full_name
        diff_result["ref"] = effective_ref
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
        """Return a window of lines from a text file.

        Args:
            full_name: "owner/repo" string.
            path: Path to the file in the repository.
            ref: Git ref (branch, tag, or SHA). Defaults to "main".
            start_line: 1-based line number to start from.
            max_lines: Maximum number of lines to return in this slice.

        Returns:
            A dict with:
                - full_name, path, ref
                - start_line, end_line, max_lines
                - total_lines
                - has_more_above / has_more_below
                - lines: list of {"line": int, "text": str}
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
            }

        start_idx = min(max(start_line - 1, 0), total_lines - 1)
        end_idx = min(start_idx + max_lines, total_lines)

        slice_lines = [
            {"line": i + 1, "text": all_lines[i]}
            for i in range(start_idx, end_idx)
        ]

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

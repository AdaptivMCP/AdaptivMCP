from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol
import difflib

# Reuse GitHub helpers from the core server implementation. These are defined
# in main.py before extra_tools is imported, so this import is safe.
from main import _github_request, _resolve_file_sha, GitHubAPIError


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
    apply_patch_and_open_pr.
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

        # Resolve the current file SHA so we can issue a DELETE via the
        # Contents API. We piggyback on the existing _resolve_file_sha helper
        # rather than re-implementing the logic here.
        sha = await _resolve_file_sha(full_name, path, branch)
        if sha is None:
            if if_missing == "noop":
                return {
                    "status": "skipped",
                    "reason": "file_not_found",
                    "full_name": full_name,
                    "path": path,
                    "branch": branch,
                    "message": (
                        f"File {path!r} not found in {full_name}@{branch}; nothing to delete."
                    ),
                }
            raise GitHubAPIError(
                f"File {path!r} not found in {full_name}@{branch}; cannot delete."
            )

        payload = {
            "message": message,
            "sha": sha,
            "branch": branch,
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
            "path": path,
            "branch": branch,
            "commit": result,
        }

    @mcp_tool(
        write_action=False,
        description=(
            "Build a unified diff from original and updated file content. "
            "Useful for large files where sending only a patch to apply_patch_and_open_pr "
            "is safer than sending full file contents."
        ),
        tags=["github", "read", "diff"],
    )
    def build_unified_diff(
        original: str,
        updated: str,
        path: str = "file.txt",
        context_lines: int = 3,
        show_whitespace: bool = False,
    ) -> Dict[str, Any]:
        """Construct a unified diff for a single file.

        Args:
            original: The current file content.
            updated: The desired new file content.
            path: Path of the file in the repository (used for diff headers).
            context_lines: Number of context lines in the diff (default 3).
            show_whitespace: If true, also return a human-oriented preview with
                visible whitespace characters. This preview is *not* meant to be
                applied; use the `patch` value for apply_patch_and_open_pr.

        Returns:
            A dict containing at least:
                - patch: unified diff as a string suitable for git apply /
                  apply_patch_and_open_pr.
                - preview (optional): a diff string with visible whitespace
                  markers for debugging.
        """

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
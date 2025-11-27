from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol

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
        description=("Delete a file from a GitHub repository using the Contents API."
                     " Call ensure_branch first if you want to delete on a dedicated branch."),
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

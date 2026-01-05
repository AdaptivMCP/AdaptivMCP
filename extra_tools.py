"""Optional extra tools.

These tools are registered opportunistically at server startup via
``register_extra_tools_if_available``.

Important: avoid importing ``main`` here. The main module imports the server,
and the server imports this module to register tools. Importing ``main`` would
create a cycle, causing registration to fail and the tools to be omitted.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Protocol

from github_mcp.github_content import _decode_github_content, _resolve_file_sha
from github_mcp.http_clients import _github_request
from github_mcp.utils import _effective_ref_for_repo, _normalize_repo_path_for_repo
from github_mcp.workspace import _workspace_path


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

    return "Adaptiv Connected."


async def get_file_slice(
    full_name: str,
    path: str,
    ref: str | None = None,
    start_line: int = 1,
    max_lines: int | None = None,
) -> Dict[str, Any]:
    """Fetch a line-range slice of a text file."""

    if start_line < 1:
        raise ValueError("start_line must be >= 1")
    if max_lines is not None and max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_path = _normalize_repo_path_for_repo(full_name, path)

    decoded = await _decode_github_content(full_name, normalized_path, effective_ref)
    text = decoded.get("text", "")
    all_lines = str(text).splitlines(keepends=False)
    total_lines = len(all_lines)

    if total_lines == 0:
        return {
            "full_name": full_name,
            "path": normalized_path,
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
    end_idx = total_lines

    slice_lines = [
        {"line": i + 1, "text": all_lines[i]} for i in range(start_idx, end_idx)
    ]

    return {
        "full_name": full_name,
        "path": normalized_path,
        "ref": effective_ref,
        "start_line": start_idx + 1,
        "end_line": end_idx,
        "max_lines": max_lines,
        "total_lines": total_lines,
        "has_more_above": start_idx > 0,
        "has_more_below": False,
        "lines": slice_lines,
    }




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
    normalized_path = _normalize_repo_path_for_repo(full_name, path)

    sha = await _resolve_file_sha(full_name, normalized_path, effective_branch)
    if sha is None:
        if if_missing == "noop":
            return {
                "status": "noop",
                "full_name": full_name,
                "path": normalized_path,
                "branch": effective_branch,
            }
        raise FileNotFoundError(
            f"File not found: {normalized_path} on {effective_branch}"
        )

    payload = {"message": message, "sha": sha, "branch": effective_branch}
    result = await _github_request(
        "DELETE",
        f"/repos/{full_name}/contents/{normalized_path}",
        json_body=payload,
        expect_json=True,
    )

    return {
        "status": "deleted",
        "full_name": full_name,
        "path": normalized_path,
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

    workspace_root = Path(_workspace_path(full_name, effective_ref)).resolve()
    workspace_candidate = Path(workspace_path)
    if workspace_candidate.is_absolute():
        workspace_file = workspace_candidate.resolve()
    else:
        workspace_file = (workspace_root / workspace_path).resolve()

    if (
        workspace_root not in workspace_file.parents
        and workspace_file != workspace_root
    ):
        raise ValueError("workspace_path must stay within the workspace root")

    if not workspace_file.is_file():
        raise FileNotFoundError(
            f"Workspace file {workspace_path!r} not found in {workspace_root!r}"
        )

    normalized_target_path = _normalize_repo_path_for_repo(full_name, target_path)

    content_bytes = workspace_file.read_bytes()
    encoded = base64.b64encode(content_bytes).decode("ascii")

    sha = await _resolve_file_sha(full_name, normalized_target_path, effective_ref)

    payload: Dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": effective_ref,
    }
    if sha is not None:
        payload["sha"] = sha

    result = await _github_request(
        "PUT",
        f"/repos/{full_name}/contents/{normalized_target_path}",
        json_body=payload,
        expect_json=True,
    )

    relative_workspace_path = workspace_file.relative_to(workspace_root).as_posix()

    return {
        "full_name": full_name,
        "branch": effective_ref,
        "workspace_path": relative_workspace_path,
        "target_path": normalized_target_path,
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

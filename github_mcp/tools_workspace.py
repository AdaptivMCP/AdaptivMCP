"""Workspace mirror tool surface (developer-facing).

This module re-exports the persistent-repo-mirror (workspace clone) tools under
a stable import path for callers and tests. The actual implementations live
under `github_mcp.workspace_tools.*` and are registered via `@mcp_tool` at
import time.

Developer notes:
- Importing this module eagerly imports all workspace_tools submodules to ensure
  newly-added tools are registered.
- Tools are designed to be called by an MCP client or via the HTTP tool registry
  endpoints; return values are JSON-serializable dict payloads or scalars.
"""

from __future__ import annotations

import importlib
import pkgutil
import uuid

from github_mcp.config import BASE_LOGGER
from github_mcp.server import CONTROLLER_REPO, _structured_tool_error, mcp_tool
from github_mcp.utils import _default_branch_for_repo, _effective_ref_for_repo
from github_mcp.workspace import _workspace_path
from github_mcp.workspace_tools import _shared as _shared
from github_mcp.workspace_tools import clone as _clone
from github_mcp.workspace_tools import commands as _commands
from github_mcp.workspace_tools import commit as _commit
from github_mcp.workspace_tools import fs as _fs
from github_mcp.workspace_tools import git_ops as _git_ops
from github_mcp.workspace_tools import listing as _listing
from github_mcp.workspace_tools import pr as _pr
from github_mcp.workspace_tools import suites as _suites

LOGGER = BASE_LOGGER.getChild("tools_workspace")


def _import_all_workspace_tool_modules() -> None:
    """Eagerly import every module under ``github_mcp.workspace_tools``.

    Tool registration is side-effect based (the @mcp_tool decorator executes at
    import time). The stable surface below imports a curated subset of modules
    for backwards compatibility, but new tool modules can be added over time.

    Importing the full package ensures every @mcp_tool-decorated function is
    registered and therefore exposed via the MCP server tool registry.
    """

    import github_mcp.workspace_tools as _pkg

    for mod in pkgutil.iter_modules(getattr(_pkg, "__path__", []) or []):
        name = getattr(mod, "name", "")
        if not name or name.startswith("_"):
            continue
        module_name = f"{_pkg.__name__}.{name}"
        LOGGER.info("Registering workspace tool module %s", module_name)
        importlib.import_module(module_name)


# Ensure all workspace tools are registered (including newly-added modules).
_import_all_workspace_tool_modules()

# helpers
_safe_branch_slug = _shared._safe_branch_slug
_run_shell_ok = _shared._run_shell_ok
_git_state_markers = _shared._git_state_markers
_diagnose_workspace_branch = _shared._diagnose_workspace_branch
_delete_branch_via_workspace = _shared._delete_branch_via_workspace
_workspace_deps = _shared._workspace_deps
_resolve_full_name = _shared._resolve_full_name
_resolve_ref = _shared._resolve_ref

# compatibility constants

# tools
ensure_workspace_clone = _clone.ensure_workspace_clone

_workspace_safe_join = _fs._workspace_safe_join
_workspace_read_text = _fs._workspace_read_text
_workspace_write_text = _fs._workspace_write_text
get_workspace_file_contents = _fs.get_workspace_file_contents
get_workspace_files_contents = _fs.get_workspace_files_contents
set_workspace_file_contents = _fs.set_workspace_file_contents
edit_workspace_text_range = _fs.edit_workspace_text_range
edit_workspace_line = _fs.edit_workspace_line
replace_workspace_text = _fs.replace_workspace_text
apply_patch = _fs.apply_patch
delete_workspace_paths = _fs.delete_workspace_paths
move_workspace_paths = _fs.move_workspace_paths
apply_workspace_operations = _fs.apply_workspace_operations
compare_workspace_files = _fs.compare_workspace_files

list_workspace_files = _listing.list_workspace_files
search_workspace = _listing.search_workspace

render_shell = _commands.render_shell
terminal_command = _commands.terminal_command
run_python = _commands.run_python

workspace_create_branch = _git_ops.workspace_create_branch
workspace_delete_branch = _git_ops.workspace_delete_branch
workspace_self_heal_branch = _git_ops.workspace_self_heal_branch
workspace_sync_status = _git_ops.workspace_sync_status
workspace_sync_to_remote = _git_ops.workspace_sync_to_remote
workspace_sync_bidirectional = _git_ops.workspace_sync_bidirectional

commit_workspace = _commit.commit_workspace
commit_workspace_files = _commit.commit_workspace_files
get_workspace_changes_summary = _commit.get_workspace_changes_summary
build_pr_summary = _commit.build_pr_summary

run_tests = _suites.run_tests
run_quality_suite = _suites.run_quality_suite
run_lint_suite = _suites.run_lint_suite

commit_and_open_pr_from_workspace = _pr.commit_and_open_pr_from_workspace

__all__ = [
    "uuid",
    "CONTROLLER_REPO",
    "_structured_tool_error",
    "mcp_tool",
    "_default_branch_for_repo",
    "_effective_ref_for_repo",
    "_workspace_path",
    "_safe_branch_slug",
    "_run_shell_ok",
    "_git_state_markers",
    "_diagnose_workspace_branch",
    "_delete_branch_via_workspace",
    "_workspace_deps",
    "_resolve_full_name",
    "_resolve_ref",
    "ensure_workspace_clone",
    "get_workspace_file_contents",
    "get_workspace_files_contents",
    "set_workspace_file_contents",
    "edit_workspace_text_range",
    "edit_workspace_line",
    "replace_workspace_text",
    "apply_patch",
    "delete_workspace_paths",
    "move_workspace_paths",
    "apply_workspace_operations",
    "compare_workspace_files",
    "list_workspace_files",
    "search_workspace",
    "render_shell",
    "terminal_command",
    "run_python",
    "workspace_create_branch",
    "workspace_delete_branch",
    "workspace_self_heal_branch",
    "workspace_sync_status",
    "workspace_sync_to_remote",
    "workspace_sync_bidirectional",
    "commit_workspace",
    "commit_workspace_files",
    "get_workspace_changes_summary",
    "run_tests",
    "run_quality_suite",
    "run_lint_suite",
    "build_pr_summary",
    "commit_and_open_pr_from_workspace",
]

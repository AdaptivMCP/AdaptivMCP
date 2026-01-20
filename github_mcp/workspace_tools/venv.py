"""Workspace virtualenv lifecycle tools.

The repo mirror (workspace clone) persists across calls, and so can its
associated Python virtualenv. This module exposes explicit start/stop/status
operations so callers can manage that lifecycle instead of relying on implicit
creation during command execution.

The virtualenv lives at ``<repo_dir>/.venv-mcp``.
"""

from __future__ import annotations

import os
import shlex
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import _structured_tool_error, mcp_tool
from github_mcp.utils import _normalize_timeout_seconds

from ._shared import (
    _should_install_requirements,
    _tw,
    _write_requirements_marker,
)


@mcp_tool(write_action=True)
async def workspace_venv_start(
    full_name: str,
    ref: str = "main",
    installing_dependencies: bool = False,
) -> dict[str, Any]:
    """Start (create/repair) the workspace virtualenv.

    When ``installing_dependencies`` is True, this will attempt to install
    ``dev-requirements.txt`` (if present) inside the virtualenv.
    """

    try:
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        env = await deps["prepare_temp_virtualenv"](repo_dir)

        install_log: dict[str, Any] | None = None
        if installing_dependencies:
            req_path = os.path.join(repo_dir, "dev-requirements.txt")
            venv_dir = os.path.join(repo_dir, ".venv-mcp")
            if not os.path.isfile(req_path):
                install_log = {"skipped": True, "reason": "dev-requirements.txt not found"}
            elif not _should_install_requirements(venv_dir, req_path):
                install_log = {"skipped": True, "reason": "dependencies already satisfied"}
            else:
                timeout = _normalize_timeout_seconds(
                    config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS,
                    0,
                )
                cmd = f"python -m pip install -r {shlex.quote('dev-requirements.txt')}"
                install_log = await deps["run_shell"](
                    cmd,
                    cwd=repo_dir,
                    timeout_seconds=timeout,
                    env=env,
                )
                if install_log.get("exit_code", 0) != 0:
                    stderr = install_log.get("stderr", "") or install_log.get("stdout", "")
                    raise GitHubAPIError(f"Dependency install failed: {stderr}")
                _write_requirements_marker(venv_dir, req_path)

        status = await deps["virtualenv_status"](repo_dir)
        return {
            "ref": effective_ref,
            "venv": status,
            "installed_dependencies": bool(install_log and not install_log.get("skipped")),
            "install_log": install_log,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_venv_start")


@mcp_tool(write_action=True)
async def workspace_venv_stop(
    full_name: str,
    ref: str = "main",
) -> dict[str, Any]:
    """Stop (delete) the workspace virtualenv."""

    try:
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        stopped = await deps["stop_virtualenv"](repo_dir)
        status = await deps["virtualenv_status"](repo_dir)
        return {
            "ref": effective_ref,
            "stopped": stopped,
            "venv": status,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_venv_stop")


@mcp_tool(write_action=False)
async def workspace_venv_status(
    full_name: str,
    ref: str = "main",
) -> dict[str, Any]:
    """Get status information for the workspace virtualenv."""

    try:
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        status = await deps["virtualenv_status"](repo_dir)
        return {
            "ref": effective_ref,
            "venv": status,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_venv_status")

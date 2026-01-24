"""Workspace virtualenv lifecycle tools.

The repo mirror (workspace clone) persists across calls, and so can its
associated Python virtualenv. This module exposes explicit start/stop/status
operations so callers can manage that lifecycle instead of relying on implicit
creation during command execution.

The virtualenv lives at ``<repo_dir>/.venv-mcp``.
"""

from __future__ import annotations

from typing import Any

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import (
    _maybe_install_dev_requirements,
    _tw,
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
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        env = await deps["prepare_temp_virtualenv"](repo_dir)

        install_log: dict[str, Any] | None = None
        if installing_dependencies:
            install_log, _ = await _maybe_install_dev_requirements(
                deps,
                repo_dir=repo_dir,
                cwd=repo_dir,
                env=env,
                timeout_seconds=0,
                installing_dependencies=True,
                use_temp_venv=True,
            )

        status = await deps["virtualenv_status"](repo_dir)
        return {
            "ref": effective_ref,
            "venv": status,
            "installed_dependencies": bool(
                install_log and not install_log.get("skipped")
            ),
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
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

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
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )
        status = await deps["virtualenv_status"](repo_dir)
        return {
            "ref": effective_ref,
            "venv": status,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_venv_status")

"""Eager import of main tool modules (developer-facing).

Tool registration is side-effect based: `@mcp_tool(...)` executes at import time.

This module provides a single stable import that eagerly imports all modules
under `github_mcp.main_tools` (excluding private modules) so that every tool is
registered and therefore exposed via the MCP tool registry.

This mirrors `github_mcp.tools_workspace` for workspace tool modules.
"""

from __future__ import annotations

import importlib
import pkgutil

from github_mcp.config import BASE_LOGGER

LOGGER = BASE_LOGGER.getChild("tools_main")


def _import_all_main_tool_modules() -> None:
    import github_mcp.main_tools as _pkg

    for mod in pkgutil.iter_modules(getattr(_pkg, "__path__", []) or []):
        name = getattr(mod, "name", "")
        if not name or name.startswith("_"):
            continue
        # Avoid circular import when introspection triggers eager registration.
        if name == "introspection":
            continue
        module_name = f"{_pkg.__name__}.{name}"
        LOGGER.info("Registering main tool module %s", module_name)
        importlib.import_module(module_name)


# Ensure all main tools are registered (including newly-added modules).
_import_all_main_tool_modules()


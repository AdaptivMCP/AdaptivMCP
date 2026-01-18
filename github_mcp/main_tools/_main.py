from __future__ import annotations

import importlib
from types import ModuleType


def _main() -> ModuleType:
    """Return the loaded `main` module (importing it if needed).

    Tool implementations use this to access symbols that tests monkeypatch on
    `main` (e.g. `_github_request`, constants).
    """

    try:
        return importlib.import_module("main")
    except Exception:
        # Lightweight fallback surface.
        # Ensure tools are registered even if `main` cannot be imported.
        try:
            importlib.import_module("github_mcp.tools_workspace")
        except Exception:
            pass
        try:
            importlib.import_module("github_mcp.tools_main")
        except Exception:
            pass
        return importlib.import_module("github_mcp.server")

"""Internal wiring for main tool modules (imports/registration helpers).

Tool implementations for the main MCP surface.
"""

from __future__ import annotations

import importlib
from types import ModuleType


def _main() -> ModuleType:
    """Return the loaded `main` module (importing it if needed).

    Tool implementations use this to access symbols that tests monkeypatch on
    `main` (e.g. `_github_request`, `_ensure_write_allowed`, constants).
    """

    return importlib.import_module("main")

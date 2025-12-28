"""Lightweight package shim for github_mcp.

Tests import `tools_workspace` from the package root (``from github_mcp import
tools_workspace``). To keep the public surface area small and avoid import
errors when internal helpers change, we only re-export that submodule here."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["tools_workspace"]


def __getattr__(name: str) -> Any:
    if name == "tools_workspace":
        module = importlib.import_module(f"{__name__}.tools_workspace")
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)

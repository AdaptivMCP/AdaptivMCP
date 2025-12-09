"""Lightweight package shim for github_mcp.

Tests import `tools_workspace` from the package root (``from github_mcp import
tools_workspace``). To keep the public surface area small and avoid import
errors when internal helpers change, we only re-export that submodule here."""

from __future__ import annotations

from . import tools_workspace

__all__ = ["tools_workspace"]

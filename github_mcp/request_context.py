"""Compatibility shim for request context access.

Some modules import `get_request_context` from `github_mcp.request_context`, while
the canonical implementation lives in `github_mcp.mcp_server.context`.

Keeping this module preserves backward-compatible imports and prevents test/
runtime failures during refactors.
"""

from __future__ import annotations

from github_mcp.mcp_server.context import get_request_context

__all__ = ["get_request_context"]

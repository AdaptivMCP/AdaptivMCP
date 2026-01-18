from __future__ import annotations

from github_mcp.mcp_server.context import get_request_context as canonical_get_request_context
from github_mcp.request_context import get_request_context


def test_request_context_shim_exports_canonical_function() -> None:
    # The shim should remain a stable import target while delegating to the
    # canonical implementation.
    assert get_request_context is canonical_get_request_context


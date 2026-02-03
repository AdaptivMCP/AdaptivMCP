from __future__ import annotations

import types

import pytest

import extra_tools
import github_mcp


def test_ping_extensions_returns_expected_string() -> None:
    assert extra_tools.ping_extensions() == "Adaptiv Connected."


def test_package_dir_includes_tools_workspace() -> None:
    # github_mcp defines a custom __dir__ to expose its small public surface.
    assert "tools_workspace" in dir(github_mcp)


def test_package_getattr_imports_tools_workspace() -> None:
    # Ensure __getattr__ is exercised even if earlier tests imported the submodule.
    try:
        delattr(github_mcp, "tools_workspace")
    except AttributeError:
        pass

    module = getattr(github_mcp, "tools_workspace")
    assert isinstance(module, types.ModuleType)
    assert module.__name__ == "github_mcp.tools_workspace"
    # Sanity check: tools_workspace re-exports CONTROLLER_REPO from github_mcp.server.
    assert hasattr(module, "CONTROLLER_REPO")


def test_package_getattr_unknown_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        getattr(github_mcp, "definitely_not_real")

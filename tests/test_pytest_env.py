"""Pytest environment smoke tests for the GitHub MCP server."""


def test_pytest_is_importable():
    """Ensure pytest can be imported in the runtime environment.

    This test is mainly to verify that pytest is installed and usable in the
    Render deployment used by the MCP workspace tools.
    """
    import pytest  # type: ignore[import-not-found]

    assert hasattr(pytest, "__version__")

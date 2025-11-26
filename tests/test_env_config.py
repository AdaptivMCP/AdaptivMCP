"""Environment variable configuration tests."""

import importlib
import main as main_module


def test_tool_stdout_max_chars_respects_env(monkeypatch):
    """TOOL_STDOUT_MAX_CHARS should pick up values from the environment."""

    monkeypatch.setenv("TOOL_STDOUT_MAX_CHARS", "42")
    reloaded = importlib.reload(main_module)
    try:
        assert reloaded.TOOL_STDOUT_MAX_CHARS == 42
    finally:
        monkeypatch.delenv("TOOL_STDOUT_MAX_CHARS", raising=False)
        importlib.reload(main_module)

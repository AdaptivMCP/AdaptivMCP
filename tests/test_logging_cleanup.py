import logging

from github_mcp import config


def test_in_memory_log_handlers_removed():
    assert not hasattr(config, "ERROR_LOG_HANDLER")
    assert not hasattr(config, "LOG_RECORD_HANDLER")
    assert not hasattr(config, "ERROR_LOG_CAPACITY")
    assert not hasattr(config, "LOG_RECORD_CAPACITY")


def test_custom_tool_logging_helpers_removed():
    assert not hasattr(config, "TOOLS_LOGGER")
    assert not hasattr(config, "CHAT_LEVEL")
    assert not hasattr(config, "DETAILED_LEVEL")
    assert not hasattr(logging, "CHAT")
    assert not hasattr(logging, "DETAILED")

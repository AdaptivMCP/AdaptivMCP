from github_mcp import config


def test_in_memory_log_handlers_removed():
    assert not hasattr(config, "ERROR_LOG_HANDLER")
    assert not hasattr(config, "LOG_RECORD_HANDLER")
    assert not hasattr(config, "ERROR_LOG_CAPACITY")
    assert not hasattr(config, "LOG_RECORD_CAPACITY")

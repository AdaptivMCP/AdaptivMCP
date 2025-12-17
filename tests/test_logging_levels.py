import logging

import github_mcp.config as config


def test_custom_log_levels_registered() -> None:
    assert getattr(logging, "CHAT", None) == config.CHAT_LEVEL
    assert getattr(logging, "DETAILED", None) == config.DETAILED_LEVEL
    assert logging.getLevelName(config.CHAT_LEVEL) == "CHAT"
    assert logging.getLevelName(config.DETAILED_LEVEL) == "DETAILED"


def test_logger_helpers_emit_expected_levels(caplog) -> None:
    logger = logging.getLogger("github_mcp.tests.custom_levels")

    with caplog.at_level(config.DETAILED_LEVEL):
        logger.detailed("detailed line")
        logger.chat("chat line")

    levelnames = [rec.levelname for rec in caplog.records]
    assert "DETAILED" in levelnames
    assert "CHAT" in levelnames


def test_strip_wrapping_quotes() -> None:
    assert config._strip_wrapping_quotes('"abc"') == "abc"
    assert config._strip_wrapping_quotes("'abc'") == "abc"
    assert config._strip_wrapping_quotes("abc") == "abc"
    assert config._strip_wrapping_quotes('  "abc"  ') == "abc"

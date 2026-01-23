import importlib
import io
import logging


def _reload_config(monkeypatch):
    # Ensure predictable, non-ANSI output for assertions.
    monkeypatch.setenv("HUMAN_LOGS", "1")
    monkeypatch.setenv("LOG_COLOR", "0")
    # Prefer the prefixed variant when present; explicitly disable it for tests.
    monkeypatch.setenv("ADAPTIV_MCP_LOG_COLOR", "0")
    monkeypatch.setenv("LOG_APPEND_EXTRAS", "1")
    # Keep appended blocks bounded for test stability.
    monkeypatch.setenv("LOG_EXTRAS_MAX_LINES", "200")
    monkeypatch.setenv("LOG_EXTRAS_MAX_CHARS", "20000")

    import github_mcp.config as config

    return importlib.reload(config)


def test_provider_tool_success_logs_append_human_extras_block(monkeypatch):
    config = _reload_config(monkeypatch)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(config._StructuredFormatter("%(levelname)s | %(name)s | %(message)s"))

    logger = logging.getLogger("test.provider")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info(
        "ok",
        extra={
            "event": "tool_call_completed",
            "tool": "terminal_command",
            "call_id": "call-123",
            "foo": "bar",
            "nested": {"a": 1},
        },
    )

    out = stream.getvalue()
    # Tool lifecycle events should append an "extras" block when payload logging
    # is enabled (developer-facing mode).
    assert "extras:" in out
    assert "foo: bar" in out
    # No JSON blobs.
    assert "data=" not in out
    assert "{" not in out


def test_provider_warning_logs_append_human_extras_block(monkeypatch):
    config = _reload_config(monkeypatch)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(config._StructuredFormatter("%(levelname)s | %(name)s | %(message)s"))

    logger = logging.getLogger("test.provider.warn")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    # Info-only logging policy: warnings are emitted at INFO with a severity tag.
    logger.info("warn", extra={"severity": "warning", "foo": "bar"})

    out = stream.getvalue()
    assert "extras:" in out
    assert "foo: bar" in out
    assert "data=" not in out
    assert "{" not in out


def test_truncate_text_does_not_json_dump_mappings():
    from github_mcp.mcp_server import decorators

    s = decorators._truncate_text({"b": 2, "a": 1})
    assert "a=1" in s
    assert "b=2" in s
    assert "{" not in s

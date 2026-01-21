import logging

from github_mcp import config


def test_uvicorn_healthz_filter_suppresses_healthz_logs():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "GET /healthz HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert config._UvicornHealthzFilter().filter(record) is False


def test_uvicorn_healthz_filter_allows_other_logs():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "GET /repos HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert config._UvicornHealthzFilter().filter(record) is True

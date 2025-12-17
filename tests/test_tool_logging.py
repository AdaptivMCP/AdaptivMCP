from __future__ import annotations

import logging

import pytest

from github_mcp.tool_logging import _record_github_request, _sanitize_url_for_logs


def test_sanitize_url_for_logs_strips_trailing_quote():
    assert _sanitize_url_for_logs('https://example.com/path"') == "https://example.com/path"


def test_record_github_request_emits_clickable_web_url(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    _record_github_request(
        method="GET",
        url='https://api.github.com/repos/owner/repo/contents/some/file.py?ref=main"',
        status_code=200,
        duration_ms=12,
        error=False,
    )

    msgs = [r.getMessage() for r in caplog.records if "GitHub API GET" in r.getMessage()]
    assert msgs, "expected github request log message"

    msg = msgs[-1]
    assert "web:" in msg
    assert "https://github.com/owner/repo/blob/main/some/file.py" in msg
    # URL should not be immediately followed by a quote.
    assert 'file.py"' not in msg
    # And should not be the last token in the message (helps Render autolinkers).
    assert msg.rstrip().endswith("[web]")

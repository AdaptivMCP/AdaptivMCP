from __future__ import annotations

import pytest

from github_mcp.exceptions import UsageError
from github_mcp.main_tools import web_browser


def test_validate_url_allows_https():
    assert web_browser._validate_url("https://example.com") == "https://example.com"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://10.0.0.1",
        "http://192.168.1.2",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
    ],
)
def test_validate_url_blocks_private_and_non_http(url: str):
    with pytest.raises(UsageError):
        web_browser._validate_url(url)

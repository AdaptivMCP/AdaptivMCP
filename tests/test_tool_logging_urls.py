from github_mcp.tool_logging import _derive_github_web_url, _sanitize_url_for_logs


def test_sanitize_url_strips_trailing_quote():
    raw = 'https://api.github.com/repos/o/r/contents/p.txt?ref=main"'
    assert _sanitize_url_for_logs(raw).endswith("ref=main")


def test_sanitize_url_strips_httpx_suffix():
    raw = 'https://api.github.com/repos/o/r/contents/p.txt?ref=main "HTTP/1.1 200 OK"'
    assert _sanitize_url_for_logs(raw).endswith("ref=main")


def test_derive_github_web_url_removes_quote_and_is_clickable():
    api = 'https://api.github.com/repos/Proofgate-Revocations/chatgpt-mcp-github/contents/github_mcp/config.py?ref=main"'
    web = _derive_github_web_url(api)
    assert web is not None
    assert web.endswith("/blob/main/github_mcp/config.py")
    assert '"' not in web


def test_sanitize_url_strips_unicode_trailing_quote():
    raw = "https://api.github.com/repos/o/r/contents/p.txt?ref=main”"
    assert _sanitize_url_for_logs(raw).endswith("ref=main")

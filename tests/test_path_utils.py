import pytest


class DummyURL:
    def __init__(self, path: str | None):
        self.path = path


class DummyRequest:
    def __init__(self, headers=None, path=None, scope=None):
        self.headers = headers or {}
        self.url = DummyURL(path) if path is not None else None
        self.scope = scope


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("/", ""),
        (" / ", ""),
        ("/proxy/", "/proxy"),
        ("proxy", "/proxy"),
        ("/proxy/sub/", "/proxy/sub"),
    ],
)
def test_normalize_base_path(value, expected):
    from github_mcp import path_utils

    assert path_utils.normalize_base_path(value) == expected


def test_request_base_path_prefers_forwarded_prefix():
    from github_mcp import path_utils

    request = DummyRequest(
        headers={"x-forwarded-prefix": "/proxy/"},
        path="/ignored/api",
        scope={"root_path": "/root/"},
    )

    assert path_utils.request_base_path(request, ["/api"]) == "/proxy"


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        ("/proxy/, /other/", "/proxy"),
        ("  , /proxy/sub/  , /other", "/proxy/sub"),
        (["/proxy/", "/other/"], "/proxy"),
    ],
)
def test_request_base_path_handles_forwarded_prefix_lists(header_value, expected):
    from github_mcp import path_utils

    request = DummyRequest(
        headers={"x-forwarded-prefix": header_value},
        path="/ignored/api",
        scope={"root_path": "/root/"},
    )

    assert path_utils.request_base_path(request, ["/api"]) == expected


def test_request_base_path_uses_forwarded_path_header():
    from github_mcp import path_utils

    request = DummyRequest(
        headers={"x-forwarded-path": "/proxy/path/"},
        path="/ignored/api",
        scope={"root_path": "/root/"},
    )

    assert path_utils.request_base_path(request, ["/api"]) == "/proxy/path"


@pytest.mark.parametrize(
    ("path", "suffixes", "expected"),
    [
        ("/proxy/api", ["/api"], "/proxy"),
        ("/api", ["/api"], ""),
        ("/proxy/api", ["/v1", "/api"], "/proxy"),
    ],
)
def test_request_base_path_strips_suffixes(path, suffixes, expected):
    from github_mcp import path_utils

    request = DummyRequest(path=path)

    assert path_utils.request_base_path(request, suffixes) == expected


def test_request_base_path_falls_back_to_root_path():
    from github_mcp import path_utils

    request = DummyRequest(path=None, scope={"root_path": "/root/"})

    assert path_utils.request_base_path(request, ["/api"]) == "/root"

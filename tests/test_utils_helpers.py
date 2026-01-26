from __future__ import annotations

import pytest

from github_mcp import utils


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, 30, 30),
        (True, 30, 30),
        (False, 30, 30),
        ("", 5, 5),
        ("  12 ", 5, 12),
        ("7.9", 5, 7),
        (3.7, 5, 3),
        (4, 5, 4),
        (-1, 5, 0),
        ("not-a-number", 9, 9),
    ],
)
def test_normalize_timeout_seconds(value: object, default: int, expected: int) -> None:
    assert utils._normalize_timeout_seconds(value, default) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("example.com", "example.com"),
        ("https://example.com/sse", "example.com"),
        ("http://example.com:8080/path", "example.com"),
    ],
)
def test_extract_hostname(value: str | None, expected: str | None) -> None:
    assert utils._extract_hostname(value) == expected


def test_render_external_hosts_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert utils._render_external_hosts() == []

    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "render.example.com")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://alt.example.com/path")
    assert utils._render_external_hosts() == [
        "render.example.com",
        "alt.example.com",
    ]


def test_with_numbered_lines_and_whitespace_rendering() -> None:
    numbered = utils._with_numbered_lines("alpha\nbeta")
    assert numbered == [
        {"line": 1, "text": "alpha"},
        {"line": 2, "text": "beta"},
    ]

    rendered = utils._render_visible_whitespace("a b\nc\t")
    assert rendered == "a·b⏎\nc→\t␄"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/octo/hello.git", "octo/hello"),
        ("git@github.com:octo/hello.git", "octo/hello"),
        ("git@github.com:octo/hello", "octo/hello"),
        ("", None),
        ("not-a-url", None),
    ],
)
def test_parse_github_remote_repo(remote: str, expected: str | None) -> None:
    assert utils._parse_github_remote_repo(remote) == expected

import asyncio
import pytest

from main import GitHubAPIError, _load_body_from_content_url


def test_load_body_from_sandbox_path(tmp_path):
    file_path = tmp_path / "example.txt"
    expected = b"hello sandbox"
    file_path.write_bytes(expected)

    result = asyncio.run(
        _load_body_from_content_url(f"sandbox:{file_path}", context="test")
    )

    assert result == expected


def test_load_body_from_absolute_path(tmp_path):
    file_path = tmp_path / "absolute.txt"
    expected = b"absolute content"
    file_path.write_bytes(expected)

    result = asyncio.run(
        _load_body_from_content_url(str(file_path), context="test")
    )

    assert result == expected


def test_load_body_from_invalid_scheme():
    with pytest.raises(GitHubAPIError):
        asyncio.run(
            _load_body_from_content_url("ftp://example.com/file", context="test")
        )

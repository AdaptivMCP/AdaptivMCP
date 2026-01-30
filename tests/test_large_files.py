from __future__ import annotations

from typing import Any

import pytest

from github_mcp.exceptions import GitHubAPIError
from github_mcp.main_tools import large_files


class _FakeStream:
    def __init__(self, resp: Any):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResp:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, Any] | None = None,
        chunks: list[bytes] | None = None,
        json_data: Any | None = None,
        json_raises: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self) -> Any:
        if self._json_raises:
            raise ValueError("boom")
        return self._json_data

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, resp: _FakeResp, *, raise_in_stream: Exception | None = None):
        self._resp = resp
        self._raise_in_stream = raise_in_stream
        self.last_request: dict[str, Any] | None = None

    def stream(self, method: str, url: str, *, params=None, headers=None):
        if self._raise_in_stream is not None:
            raise self._raise_in_stream
        self.last_request = {
            "method": method,
            "url": url,
            "params": params or {},
            "headers": headers or {},
        }
        return _FakeStream(self._resp)


def test_build_range_header_validation_errors() -> None:
    with pytest.raises(ValueError, match="start_byte must be >= 0"):
        large_files._build_range_header(start_byte=-1, max_bytes=10, tail_bytes=None)

    with pytest.raises(ValueError, match="tail_bytes must be > 0"):
        large_files._build_range_header(start_byte=None, max_bytes=10, tail_bytes=0)

    with pytest.raises(ValueError, match="Provide only one of start_byte or tail_bytes"):
        large_files._build_range_header(start_byte=0, max_bytes=10, tail_bytes=1)


def test_build_range_header_max_bytes_disabled_variants() -> None:
    assert (
        large_files._build_range_header(start_byte=None, max_bytes=0, tail_bytes=None)
        == ""
    )
    assert (
        large_files._build_range_header(start_byte=5, max_bytes=0, tail_bytes=None)
        == "bytes=5-"
    )
    assert (
        large_files._build_range_header(start_byte=None, max_bytes=0, tail_bytes=10)
        == "bytes=-10"
    )


def test_build_range_header_capped_variants() -> None:
    assert (
        large_files._build_range_header(start_byte=None, max_bytes=100, tail_bytes=None)
        == "bytes=0-99"
    )
    assert (
        large_files._build_range_header(start_byte=10, max_bytes=100, tail_bytes=None)
        == "bytes=10-109"
    )
    # tail_bytes is capped by max_bytes
    assert (
        large_files._build_range_header(start_byte=None, max_bytes=100, tail_bytes=150)
        == "bytes=-100"
    )
    assert (
        large_files._build_range_header(start_byte=None, max_bytes=100, tail_bytes=50)
        == "bytes=-50"
    )


@pytest.mark.anyio
async def test_get_content_metadata_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(*_args, **_kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr(large_files, "_github_request", _raise)
    assert await large_files._get_content_metadata(full_name="o/r", path="p", ref="main") == {}

    async def _bad_shape(*_args, **_kwargs):
        return {"json": ["not", "a", "dict"]}

    monkeypatch.setattr(large_files, "_github_request", _bad_shape)
    assert await large_files._get_content_metadata(full_name="o/r", path="p", ref="main") == {}

    async def _ok(*_args, **_kwargs):
        return {
            "json": {
                "sha": "abc",
                "size": 123,
                "download_url": "https://example",
                "type": "file",
            }
        }

    monkeypatch.setattr(large_files, "_github_request", _ok)
    metadata = await large_files._get_content_metadata(
        full_name="o/r", path="p", ref="main"
    )
    assert metadata == {
        "sha": "abc",
        "size": 123,
        "download_url": "https://example",
        "type": "file",
    }


@pytest.mark.anyio
async def test_get_file_excerpt_streams_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp(
        status_code=200,
        headers={
            "Content-Range": "bytes 0-4/10",
            "Accept-Ranges": "bytes",
            "ETag": '"abc"',
            "Content-Length": "5",
        },
        # Include an empty chunk to exercise the "continue" branch.
        chunks=[b"", b"abc", b"def", b"ghi"],
    )
    client = _FakeClient(resp)

    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "refs/heads/dev")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "norm.txt")
    monkeypatch.setattr(large_files, "_with_numbered_lines", lambda t: f"NUM:{t}")

    async def _fake_meta(**_kwargs):
        return {"sha": "abc", "size": 10}

    monkeypatch.setattr(large_files, "_get_content_metadata", _fake_meta)

    result = await large_files.get_file_excerpt(
        full_name="o/r",
        path="README.md",
        ref="dev",
        max_bytes=5,
        as_text=True,
        numbered_lines=True,
    )

    assert result["ref"] == "refs/heads/dev"
    assert result["path"] == "norm.txt"
    assert result["range_requested"] == "bytes=0-4"
    assert result["size"] == 5
    assert result["truncated"] is True
    assert result["text"] == "abcde"
    assert result["numbered_lines"] == "NUM:abcde"
    assert result["metadata"] == {"sha": "abc", "size": 10}
    assert result["headers"]["content_range"] == "bytes 0-4/10"

    assert client.last_request is not None
    assert client.last_request["params"]["ref"] == "refs/heads/dev"
    assert client.last_request["headers"]["Accept"] == "application/vnd.github.raw"
    assert client.last_request["headers"]["Range"] == "bytes=0-4"


@pytest.mark.anyio
async def test_get_file_excerpt_truncates_when_remaining_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First chunk fills max_bytes exactly; second chunk triggers remaining <= 0.
    resp = _FakeResp(status_code=200, chunks=[b"12345", b"z"])
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    async def _fake_meta(**_k):
        return {}

    monkeypatch.setattr(large_files, "_get_content_metadata", _fake_meta)

    result = await large_files.get_file_excerpt(
        full_name="o/r",
        path="p",
        max_bytes=5,
        as_text=True,
        numbered_lines=False,
    )

    assert result["text"] == "12345"
    assert result["truncated"] is True


@pytest.mark.anyio
async def test_get_file_excerpt_truncates_text_by_max_text_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = _FakeResp(status_code=200, chunks=[b"hello world"])
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    async def _fake_meta(**_k):
        return {}

    monkeypatch.setattr(large_files, "_get_content_metadata", _fake_meta)

    result = await large_files.get_file_excerpt(
        full_name="o/r",
        path="p",
        max_bytes=0,
        as_text=True,
        max_text_chars=3,
        numbered_lines=False,
    )

    assert result["text"] == "hel"


@pytest.mark.anyio
async def test_get_file_excerpt_tail_bytes_sets_note(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp(status_code=200, chunks=[b"hello"])
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    async def _fake_meta(**_k):
        return {}

    monkeypatch.setattr(large_files, "_get_content_metadata", _fake_meta)

    result = await large_files.get_file_excerpt(
        full_name="o/r",
        path="p",
        tail_bytes=10,
        max_bytes=100,
        as_text=False,
    )

    assert result["range_requested"] == "bytes=-10"
    assert isinstance(result["note"], str)
    assert "tail_bytes" in result["note"]


@pytest.mark.anyio
async def test_get_file_excerpt_as_text_false(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp(status_code=200, chunks=[b"hello"])
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    async def _fake_meta(**_k):
        return {}

    monkeypatch.setattr(large_files, "_get_content_metadata", _fake_meta)

    result = await large_files.get_file_excerpt(full_name="o/r", path="p", as_text=False)

    assert result["text"] is None
    assert result["numbered_lines"] is None


@pytest.mark.anyio
async def test_get_file_excerpt_http_error_includes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp(status_code=404, json_data={"message": "Not Found"})
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    with pytest.raises(GitHubAPIError, match=r"HTTP 404 - Not Found"):
        await large_files.get_file_excerpt(full_name="o/r", path="p", max_bytes=10)


@pytest.mark.anyio
async def test_get_file_excerpt_http_error_without_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResp(status_code=500, json_data=None, json_raises=True)
    client = _FakeClient(resp)
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    with pytest.raises(GitHubAPIError, match=r"HTTP 500"):
        await large_files.get_file_excerpt(full_name="o/r", path="p", max_bytes=10)


@pytest.mark.anyio
async def test_get_file_excerpt_wraps_stream_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(_FakeResp(), raise_in_stream=RuntimeError("explode"))
    monkeypatch.setattr(large_files, "_github_client_instance", lambda: client)
    monkeypatch.setattr(large_files, "_effective_ref_for_repo", lambda *_a: "main")
    monkeypatch.setattr(large_files, "_normalize_repo_path_for_repo", lambda *_a: "p")

    with pytest.raises(GitHubAPIError, match=r"Failed to stream content"):
        await large_files.get_file_excerpt(full_name="o/r", path="p", max_bytes=10)


def test_get_file_excerpt_validates_inputs() -> None:
    # Covered via the async validation test below. Keep this file free of
    # accidental non-async invocations.
    assert callable(large_files.get_file_excerpt)


@pytest.mark.anyio
async def test_get_file_excerpt_rejects_invalid_full_name_and_path() -> None:
    with pytest.raises(ValueError, match="owner/repo"):
        await large_files.get_file_excerpt(full_name="invalid", path="p")

    with pytest.raises(ValueError, match="non-empty"):
        await large_files.get_file_excerpt(full_name="o/r", path=" ")


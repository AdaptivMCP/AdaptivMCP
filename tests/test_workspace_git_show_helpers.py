from __future__ import annotations

import builtins
import io
import subprocess

import pytest

import github_mcp.workspace_tools.fs as fs


def test_read_lines_sections_unicode_decode_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # _read_lines_sections uses errors="replace", but keeps a defensive except.
    # Force the except branch by making open() raise UnicodeDecodeError.
    abs_path = str(tmp_path / "file.txt")

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom")

    monkeypatch.setattr(builtins, "open", _boom)

    res = fs._read_lines_sections(
        abs_path,
        start_line=1,
        max_sections=2,
        max_lines_per_section=3,
        max_chars_per_section=10,
        overlap_lines=1,
    )
    assert res["had_decoding_errors"] is True
    assert res["parts"] == []
    assert res["truncated"] is False


def test_sanitize_git_path_valid_and_invalid() -> None:
    assert fs._sanitize_git_path("a/b.txt") == "a/b.txt"
    assert fs._sanitize_git_path("/a/b.txt") == "a/b.txt"
    assert fs._sanitize_git_path("\\a\\b.txt") == "a/b.txt"

    with pytest.raises(ValueError):
        fs._sanitize_git_path(" ")
    with pytest.raises(ValueError):
        fs._sanitize_git_path(":bad")
    with pytest.raises(ValueError):
        fs._sanitize_git_path("-starts-with-dash")


def test_git_show_text_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    repo_dir = str(tmp_path)

    class _Proc:
        returncode = 1
        stdout = b""
        stderr = b"fatal: path 'nope.txt' does not exist in 'main'"

    def _fake_run(*args, **kwargs):  # noqa: ANN001
        return _Proc()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    res = fs._git_show_text(repo_dir, "main", "nope.txt")
    assert res["exists"] is False
    assert res["ref"] == "main"
    assert res["path"] == "nope.txt"
    assert res["error"]


def test_git_show_text_decode_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    repo_dir = str(tmp_path)

    class _Proc:
        returncode = 0
        stdout = b"hello\n\xff\xfe\xffworld\n"
        stderr = b""

    def _fake_run(*args, **kwargs):  # noqa: ANN001
        return _Proc()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    res = fs._git_show_text(repo_dir, "main", "bad.txt")
    assert res["exists"] is True
    assert res["had_decoding_errors"] is True
    assert "hello" in res["text"]


class _FakePopen:
    def __init__(
        self, stdout_bytes: bytes, stderr_bytes: bytes, *, returncode: int | None = None
    ):
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self.returncode = returncode
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        # Simulate that the process will exit after kill.
        self.returncode = 0

    def communicate(self, timeout: int | None = None):  # noqa: ANN001
        # In real Popen, communicate returns remaining content; here it's fine.
        out = self.stdout.read()
        err = self.stderr.read()
        if self.returncode is None:
            self.returncode = 0
        return out, err


def test_git_show_text_limited_validates_inputs(tmp_path) -> None:
    with pytest.raises(ValueError):
        fs._git_show_text_limited(str(tmp_path), "main", "x.txt", max_chars="nope")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        fs._git_show_text_limited(
            str(tmp_path), "main", "x.txt", max_chars=10, max_bytes="nope"
        )  # type: ignore[arg-type]


def test_git_show_text_limited_infers_byte_cap_from_chars(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_dir = str(tmp_path)

    def _fake_popen(*args, **kwargs):  # noqa: ANN001
        return _FakePopen(b"A" * 100, b"", returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    res = fs._git_show_text_limited(repo_dir, "main", "x.txt", max_chars=5)
    assert res["max_bytes"] == 20
    assert res["truncated_bytes"] is True
    assert res["text"] == "A" * 5


def test_git_show_text_limited_nonzero_returncode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_dir = str(tmp_path)

    def _fake_popen(*args, **kwargs):  # noqa: ANN001
        return _FakePopen(b"", b"fatal: bad object", returncode=1)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    res = fs._git_show_text_limited(
        repo_dir, "main", "x.txt", max_chars=10, max_bytes=10
    )
    assert res["exists"] is False
    assert res["truncated"] is False
    assert res["error"]


def test_git_show_text_limited_truncates_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_dir = str(tmp_path)

    def _fake_popen(*args, **kwargs):  # noqa: ANN001
        # 100 bytes of text; max_bytes forces truncation.
        return _FakePopen(b"A" * 100, b"", returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    res = fs._git_show_text_limited(
        repo_dir, "main", "x.txt", max_chars=0, max_bytes=10
    )
    assert res["exists"] is True
    assert res["truncated"] is True
    assert res["truncated_bytes"] is True
    assert res["truncated_chars"] is False
    assert res["size_bytes"] == 10
    assert len(res["text"]) == 10


def test_git_show_text_limited_truncates_bytes_ignores_kill_returncode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_dir = str(tmp_path)

    class _KillNonzeroPopen(_FakePopen):
        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

    def _fake_popen(*args, **kwargs):  # noqa: ANN001
        return _KillNonzeroPopen(b"A" * 100, b"", returncode=None)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    res = fs._git_show_text_limited(
        repo_dir, "main", "x.txt", max_chars=0, max_bytes=10
    )
    assert res["exists"] is True
    assert res["truncated_bytes"] is True


def test_git_show_text_limited_truncates_chars(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    repo_dir = str(tmp_path)

    def _fake_popen(*args, **kwargs):  # noqa: ANN001
        return _FakePopen("hello world".encode("utf-8"), b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    res = fs._git_show_text_limited(
        repo_dir, "main", "x.txt", max_chars=5, max_bytes=1024
    )
    assert res["exists"] is True
    assert res["truncated"] is True
    assert res["truncated_chars"] is True
    assert res["text"] == "hello"

import os

import pytest

from github_mcp.workspace_tools import fs


def test_read_lines_excerpt_strips_crlf_and_cr(tmp_path) -> None:
    p = tmp_path / "crlf.txt"
    p.write_bytes(b"one\r\ntwo\r\nthree\r\n")

    out = fs._read_lines_excerpt(
        str(p),
        start_line=1,
        max_lines=10,
        max_chars=10_000,
    )
    assert [line["text"] for line in out["lines"]] == ["one", "two", "three"]
    assert out["truncated"] is False

    p2 = tmp_path / "cr.txt"
    p2.write_bytes(b"one\rtwo\rthree\r")
    out2 = fs._read_lines_excerpt(
        str(p2),
        start_line=1,
        max_lines=10,
        max_chars=10_000,
    )
    # Universal newlines translate \r to line boundaries.
    assert [line["text"] for line in out2["lines"]] == ["one", "two", "three"]


def test_read_lines_excerpt_char_limit_truncates_mid_line(tmp_path) -> None:
    p = tmp_path / "long.txt"
    p.write_text("abcdef\nxyz\n", encoding="utf-8")

    out = fs._read_lines_excerpt(
        str(p),
        start_line=1,
        max_lines=10,
        max_chars=3,
    )
    assert out["truncated"] is True
    assert out["lines"][0]["text"] == "abc"
    assert out["lines"][0]["truncated"] is True


def test_workspace_read_text_limited_binary_returns_stable_payload(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bin_path = repo / "bin.dat"
    # Include a null byte to trigger binary detection.
    bin_path.write_bytes(b"\x00\x01\x02hello")

    out = fs._workspace_read_text_limited(
        str(repo),
        "bin.dat",
        max_chars=100,
        max_bytes=100,
    )
    assert out["exists"] is True
    assert out["is_binary"] is True
    assert out["encoding"] == "binary"
    assert out["text"] == ""
    assert out["size_bytes"] == bin_path.stat().st_size


def test_workspace_safe_join_accepts_repo_root_aliases(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert fs._workspace_safe_join(str(repo), "") == os.path.realpath(str(repo))
    assert fs._workspace_safe_join(str(repo), "   ") == os.path.realpath(str(repo))
    assert fs._workspace_safe_join(str(repo), "/") == os.path.realpath(str(repo))


def test_workspace_safe_join_rejects_escape_and_colon(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="within the repository"):
        fs._workspace_safe_join(str(repo), "../secrets.txt")

    with pytest.raises(ValueError, match=":"):
        fs._workspace_safe_join(str(repo), "foo:bar.txt")

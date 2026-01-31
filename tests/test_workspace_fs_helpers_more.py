from __future__ import annotations

import os

import pytest

import github_mcp.workspace_tools.fs as fs


def test_workspace_read_text_limited_missing(tmp_path: pytest.TempPathFactory) -> None:
    repo_dir = str(tmp_path)
    res = fs._workspace_read_text_limited(repo_dir, "nope.txt", max_chars=10)
    assert res["exists"] is False
    assert res["text"] == ""
    assert res["truncated"] is False


def test_workspace_read_text_limited_binary_detection(
    tmp_path: pytest.TempPathFactory,
) -> None:
    repo_dir = str(tmp_path)
    p = os.path.join(repo_dir, "bin.dat")
    with open(p, "wb") as f:
        f.write(b"ABC\x00DEF" * 100)

    res = fs._workspace_read_text_limited(
        repo_dir, "bin.dat", max_chars=10, max_bytes=64
    )
    assert res["exists"] is True
    assert res["encoding"] == "binary"
    assert res.get("is_binary") is True
    assert res["text"] == ""
    assert res["size_bytes"] > 0
    assert res["truncated"] is True  # size > max_bytes
    assert res["truncated_bytes"] is True
    assert res["truncated_chars"] is False


def test_workspace_read_text_limited_text_decode_and_truncation(
    tmp_path: pytest.TempPathFactory,
) -> None:
    repo_dir = str(tmp_path)
    p = os.path.join(repo_dir, "bad.txt")
    # Invalid UTF-8 to trigger replacement decode.
    with open(p, "wb") as f:
        f.write(b"hello\n" + b"\xff\xfe\xff" + b"world\n")

    res = fs._workspace_read_text_limited(
        repo_dir, "bad.txt", max_chars=6, max_bytes=1024
    )
    assert res["exists"] is True
    assert res["encoding"] == "utf-8"
    assert res["had_decoding_errors"] is True
    assert res["truncated"] is True
    assert res["truncated_chars"] is True
    assert len(res["text"]) == 6


def test_read_lines_excerpt_truncates_on_char_budget(
    tmp_path: pytest.TempPathFactory,
) -> None:
    p = os.path.join(str(tmp_path), "a.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("one\ntwo\nthree\n")

    res = fs._read_lines_excerpt(p, start_line=1, max_lines=10, max_chars=5)
    assert res["truncated"] is True
    assert res["lines"][0]["text"] == "one"
    # Second line is clipped to remaining budget (5-3=2).
    assert res["lines"][1]["text"] == "tw"
    assert res["lines"][1]["truncated"] is True


def test_sections_from_line_iter_overlap_and_next_start_line() -> None:
    lines = [f"L{i}\n" for i in range(1, 11)]

    res = fs._sections_from_line_iter(
        iter(lines),
        start_line=1,
        max_sections=2,
        max_lines_per_section=3,
        max_chars_per_section=10_000,
        overlap_lines=1,
    )

    assert res["truncated"] is True
    assert len(res["parts"]) == 2
    assert res["parts"][0]["start_line"] == 1
    assert res["parts"][0]["end_line"] == 3
    # The second part starts with overlap from the previous part.
    assert res["parts"][1]["start_line"] == 3
    assert res["parts"][1]["lines"][0]["line"] == 3
    assert res["next_start_line"] == 5  # last_end(4) - overlap(1) + 1


def test_sections_from_line_iter_single_long_line_is_clipped() -> None:
    lines = ["A" * 50 + "\n", "B\n"]
    res = fs._sections_from_line_iter(
        iter(lines),
        start_line=1,
        max_sections=5,
        max_lines_per_section=10,
        max_chars_per_section=10,
        overlap_lines=0,
    )

    assert res["truncated"] is True
    assert len(res["parts"]) >= 1
    first = res["parts"][0]["lines"][0]
    assert first["line"] == 1
    assert first.get("truncated") is True
    assert len(first["text"]) == 9  # max_chars_per_section - 1 (reserve newline)
    assert res["next_start_line"] == 2


def test_sanitize_git_ref_valid_and_invalid() -> None:
    assert fs._sanitize_git_ref("main") == "main"

    with pytest.raises(ValueError):
        fs._sanitize_git_ref(" ")
    with pytest.raises(ValueError):
        fs._sanitize_git_ref("bad ref")
    with pytest.raises(ValueError):
        fs._sanitize_git_ref("-starts-with-dash")
    with pytest.raises(ValueError):
        fs._sanitize_git_ref("nul\x00here")


def test_pos_to_offset_boundaries() -> None:
    lines = ["abc\n", "de"]

    # After 'c' (before newline)
    assert fs._pos_to_offset(lines, 1, 4) == 3
    # Beginning of second line
    assert fs._pos_to_offset(lines, 2, 1) == 4
    # EOF sentinel
    assert fs._pos_to_offset(lines, 3, 1) == 6

    with pytest.raises(ValueError):
        fs._pos_to_offset(lines, 3, 2)
    with pytest.raises(ValueError):
        fs._pos_to_offset(lines, 1, 99)


def test_apply_workspace_operations_write_action_resolver_more() -> None:
    assert fs._apply_workspace_operations_write_action_resolver(None) is True

    assert (
        fs._apply_workspace_operations_write_action_resolver(
            {"preview_only": True, "operations": []}
        )
        is False
    )

    assert (
        fs._apply_workspace_operations_write_action_resolver(
            {"operations": [{"op": "read_sections", "path": "x"}]}
        )
        is False
    )

    assert (
        fs._apply_workspace_operations_write_action_resolver(
            {"operations": [{"op": "write", "path": "x", "content": "y"}]}
        )
        is True
    )

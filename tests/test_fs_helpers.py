import os

import pytest

from github_mcp.workspace_tools import fs as workspace_fs


def test_normalize_workspace_operation_aliases_and_conveniences():
    # operation key + alias + mkdirp defaults.
    op = workspace_fs._normalize_workspace_operation(
        {"operation": "mkdirp", "path": "a/b"}
    )
    assert op["op"] == "mkdir"
    assert op["parents"] is True
    assert "operation" not in op

    # Case-insensitive aliases.
    op2 = workspace_fs._normalize_workspace_operation(
        {"op": "Mv", "src": "a", "dst": "b"}
    )
    assert op2["op"] == "move"

    op3 = workspace_fs._normalize_workspace_operation({"op": "rm", "path": "x"})
    assert op3["op"] == "delete"


def test_normalize_workspace_operation_errors():
    with pytest.raises(TypeError):
        workspace_fs._normalize_workspace_operation("not-a-mapping")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        workspace_fs._normalize_workspace_operation({})

    with pytest.raises(ValueError):
        workspace_fs._normalize_workspace_operation({"op": "   "})


def test_normalize_workspace_operations_errors():
    with pytest.raises(TypeError):
        workspace_fs._normalize_workspace_operations("nope")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        workspace_fs._normalize_workspace_operations(
            [{"op": "write"}, "bad"]  # type: ignore[list-item]
        )


def test_looks_like_diff():
    assert workspace_fs._looks_like_diff("diff --git a/x b/x\n") is True
    assert workspace_fs._looks_like_diff("+++ b/x\n--- a/x\n@@ -1 +1 @@\n") is True
    assert workspace_fs._looks_like_diff("just some text\n") is False
    assert workspace_fs._looks_like_diff("") is False
    assert workspace_fs._looks_like_diff(None) is False  # type: ignore[arg-type]


def test_workspace_safe_join_root_and_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    root = os.path.realpath(str(repo))
    assert workspace_fs._workspace_safe_join(str(repo), "") == root
    assert workspace_fs._workspace_safe_join(str(repo), "   ") == root
    assert workspace_fs._workspace_safe_join(str(repo), "/") == root

    # Relative paths: normalize separators.
    expected = os.path.realpath(os.path.join(str(repo), "a", "b.txt"))
    assert workspace_fs._workspace_safe_join(str(repo), "a\\b.txt") == expected

    # Absolute paths outside the repo are rejected.
    abs_target = os.path.realpath(str(tmp_path / "outside.txt"))
    with pytest.raises(ValueError, match="within the repository"):
        workspace_fs._workspace_safe_join(str(repo), abs_target)

    # Traversal outside the repo is rejected.
    with pytest.raises(ValueError, match="within the repository"):
        workspace_fs._workspace_safe_join(str(repo), "../")


def test_workspace_read_text_decoding_errors(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "bad.txt"
    p.write_bytes(b"\xff\xfe\xff")

    out = workspace_fs._workspace_read_text(str(repo), "bad.txt")
    assert out["exists"] is True
    assert out["had_decoding_errors"] is True
    assert out["encoding"] == "utf-8"
    assert out["size_bytes"] == 3
    # Replacement characters should exist.
    assert "\ufffd" in out["text"]


def test_workspace_read_text_limited_truncation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "big.txt"
    p.write_text("abcdef" * 100, encoding="utf-8")

    out = workspace_fs._workspace_read_text_limited(str(repo), "big.txt", max_chars=5)
    assert out["exists"] is True
    assert out["encoding"] == "utf-8"
    assert out["truncated"] is True
    assert out["truncated_chars"] is True
    assert len(out["text"]) == 5
    assert isinstance(out["text_digest"], str) and out["text_digest"]


def test_workspace_read_text_limited_binary_detection(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "bin.dat"
    # Include a null byte to trigger binary heuristic.
    p.write_bytes(b"abc\x00def" * 100)

    out = workspace_fs._workspace_read_text_limited(
        str(repo), "bin.dat", max_chars=100, max_bytes=10
    )
    assert out["exists"] is True
    assert out["is_binary"] is True
    assert out["encoding"] == "binary"
    assert out["text"] == ""
    # If the file is larger than max_bytes, it should flag truncated_bytes.
    assert out["truncated_bytes"] is True
    assert out["truncated"] is True


def test_is_probably_binary_missing_file_returns_false(tmp_path):
    missing = tmp_path / "nope.bin"
    assert workspace_fs._is_probably_binary(str(missing)) is False


def test_read_lines_excerpt_basic_and_truncation(tmp_path):
    p = tmp_path / "lines.txt"
    p.write_text("a\n" + "b\n" + "c\n" + "d\n", encoding="utf-8")

    out = workspace_fs._read_lines_excerpt(
        str(p), start_line=2, max_lines=2, max_chars=100
    )
    assert out["start_line"] == 2
    assert out["end_line"] == 3
    assert [ln["text"] for ln in out["lines"]] == ["b", "c"]
    # We reached max_lines while there are more lines available.
    assert out["truncated"] is True

    # Truncate by chars.
    out2 = workspace_fs._read_lines_excerpt(
        str(p), start_line=1, max_lines=10, max_chars=2
    )
    assert out2["truncated"] is True

    with pytest.raises(ValueError):
        workspace_fs._read_lines_excerpt(str(p), start_line=0, max_lines=1, max_chars=1)
    with pytest.raises(ValueError):
        workspace_fs._read_lines_excerpt(str(p), start_line=1, max_lines=0, max_chars=1)
    with pytest.raises(ValueError):
        workspace_fs._read_lines_excerpt(str(p), start_line=1, max_lines=1, max_chars=0)


def test_read_lines_excerpt_exact_max_lines_not_truncated(tmp_path):
    p = tmp_path / "exact.txt"
    p.write_text("first\nsecond\n", encoding="utf-8")

    out = workspace_fs._read_lines_excerpt(
        str(p), start_line=1, max_lines=2, max_chars=100
    )
    assert [ln["text"] for ln in out["lines"]] == ["first", "second"]
    assert out["truncated"] is False

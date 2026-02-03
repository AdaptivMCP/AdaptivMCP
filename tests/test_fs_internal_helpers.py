import os

import pytest

import github_mcp.workspace_tools.fs as fs


def test_normalize_workspace_operation_aliases_and_mkdirp_defaults():
    assert fs._normalize_workspace_operation({"op": "rm", "path": "a"})["op"] == "delete"
    assert fs._normalize_workspace_operation({"operation": "mv", "src": "a", "dst": "b"})[
        "op"
    ] == "move"

    out = fs._normalize_workspace_operation({"op": "mkdirp", "path": "x"})
    assert out["op"] == "mkdir"
    assert out["parents"] is True


def test_normalize_workspace_operation_validation():
    with pytest.raises(TypeError):
        fs._normalize_workspace_operation(["not-a-mapping"])  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        fs._normalize_workspace_operation({"op": "   "})


def test_normalize_workspace_operations_validation():
    with pytest.raises(TypeError):
        fs._normalize_workspace_operations({"op": "read"})  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        fs._normalize_workspace_operations([{"op": "read"}, "nope"])  # type: ignore[list-item]


def test_looks_like_diff_detection():
    assert fs._looks_like_diff("diff --git a/x b/x\n@@ -1 +1 @@") is True
    assert fs._looks_like_diff("--- a/x\n+++ b/x\n@@") is True
    assert fs._looks_like_diff("hello\nworld") is False
    assert fs._looks_like_diff(123) is False  # type: ignore[arg-type]


def test_workspace_safe_join_semantics(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Empty path and "/" mean repo root.
    assert fs._workspace_safe_join(str(repo_dir), "") == os.path.realpath(repo_dir)
    assert fs._workspace_safe_join(str(repo_dir), "   ") == os.path.realpath(repo_dir)
    assert fs._workspace_safe_join(str(repo_dir), "/") == os.path.realpath(repo_dir)

    # Normalizes slashes and '.' segments.
    joined = fs._workspace_safe_join(str(repo_dir), "./a//b\\c")
    assert joined.endswith(os.path.join("a", "b", "c"))

    # Intentionally permissive: allow traversal outside repo.
    outside = fs._workspace_safe_join(str(repo_dir), "../outside.txt")
    assert outside == os.path.realpath(tmp_path / "outside.txt")

    # Intentionally permissive: absolute paths pass through.
    abs_target = os.path.realpath(tmp_path / "abs.txt")
    assert fs._workspace_safe_join(str(repo_dir), abs_target) == abs_target


def test_workspace_read_text_limited_text_truncation(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    p = repo_dir / "t.txt"
    p.write_text("a" * 50, encoding="utf-8")

    out = fs._workspace_read_text_limited(str(repo_dir), "t.txt", max_chars=10, max_bytes=15)
    assert out["exists"] is True
    assert out["encoding"] == "utf-8"
    assert out["text"] == "a" * 10
    assert out["truncated"] is True
    assert out["truncated_bytes"] is True
    assert out["truncated_chars"] is True
    assert isinstance(out.get("text_digest"), str)


def test_workspace_read_text_limited_binary_detection_and_digest(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    p = repo_dir / "bin.dat"
    # Contains null bytes => binary
    p.write_bytes(b"A\x00B" * 200)

    out = fs._workspace_read_text_limited(str(repo_dir), "bin.dat", max_chars=100, max_bytes=20)
    assert out["exists"] is True
    assert out["encoding"] == "binary"
    assert out["is_binary"] is True
    assert out["text"] == ""
    assert out["truncated"] is True
    assert out["truncated_bytes"] is True
    assert out["truncated_chars"] is False
    assert isinstance(out.get("text_digest"), str)


def test_read_lines_excerpt_validation_and_truncation(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("one\n" + "two\n" + "three\n" + "four\n", encoding="utf-8")

    with pytest.raises(ValueError):
        fs._read_lines_excerpt(str(p), start_line=0, max_lines=1, max_chars=10)

    with pytest.raises(ValueError):
        fs._read_lines_excerpt(str(p), start_line=1, max_lines=0, max_chars=10)

    with pytest.raises(ValueError):
        fs._read_lines_excerpt(str(p), start_line=1, max_lines=1, max_chars=0)
    out = fs._read_lines_excerpt(str(p), start_line=2, max_lines=2, max_chars=100)
    assert [x["text"] for x in out["lines"]] == ["two", "three"]
    assert out["start_line"] == 2
    assert out["end_line"] == 3
    # max_lines stops iteration early, so "truncated" is True when more lines exist.
    assert out["truncated"] is True


    # Char cap truncates within a line.
    out2 = fs._read_lines_excerpt(str(p), start_line=1, max_lines=10, max_chars=5)
    assert out2["truncated"] is True
    assert out2["lines"][0]["text"] == "one"
    assert out2["lines"][1]["truncated"] is True


def test_sections_from_line_iter_overlap_and_limits():
    lines = [f"L{i}\n" for i in range(1, 8)]
    out = fs._sections_from_line_iter(
        iter(lines),
        start_line=1,
        max_sections=2,
        max_lines_per_section=3,
        max_chars_per_section=10_000,
        overlap_lines=1,
    )

    assert out["truncated"] is True
    assert len(out["parts"]) == 2
    assert out["parts"][0]["start_line"] == 1
    assert out["parts"][0]["end_line"] == 3
    # Overlap seeds the next section with the last line from the previous section.
    assert out["parts"][1]["lines"][0]["line"] == 3
    assert out["parts"][1]["lines"][0]["text"] == "L3"
    # Continuation begins at the last_end - overlap + 1.
    assert out["next_start_line"] == 5



def test_sections_from_line_iter_single_long_line_clip_sets_next_start():
    lines = ["X" * 50 + "\n", "Y\n"]
    out = fs._sections_from_line_iter(
        iter(lines),
        start_line=1,
        max_sections=5,
        max_lines_per_section=200,
        max_chars_per_section=10,
        overlap_lines=0,
    )

    assert out["truncated"] is True
    assert out["next_start_line"] == 2
    assert len(out["parts"]) == 1
    assert out["parts"][0]["lines"][0]["truncated"] is True
    assert len(out["parts"][0]["lines"][0]["text"]) == 9

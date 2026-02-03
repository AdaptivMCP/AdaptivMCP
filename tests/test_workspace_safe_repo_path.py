import os

import pytest

from github_mcp import workspace
from github_mcp.exceptions import GitHubAPIError


def test_safe_repo_path_normalizes_relative_segments(tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    resolved = workspace._safe_repo_path(str(repo_dir), "./folder/./file.txt")
    assert resolved == os.path.realpath(repo_dir / "folder" / "file.txt")


def test_safe_repo_path_rejects_empty_path(tmp_path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    with pytest.raises(GitHubAPIError):
        workspace._safe_repo_path(str(repo_dir), "   ")


def test_safe_repo_path_rejects_windows_absolute_paths_on_posix(tmp_path) -> None:
    if os.name == "nt":
        pytest.skip("Windows path handling only relevant on non-Windows hosts")

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    with pytest.raises(GitHubAPIError):
        workspace._safe_repo_path(str(repo_dir), "C:\\temp\\file.txt")


def test_maybe_unescape_unified_diff_unescapes_diff_payload() -> None:
    raw = (
        "diff --git a/file.txt b/file.txt\\n"
        "--- a/file.txt\\n"
        "+++ b/file.txt\\n"
        "@@ -1 +1 @@\\n"
        "-old\\n"
        "+new\\n"
    )
    resolved = workspace._maybe_unescape_unified_diff(raw)
    assert "diff --git" in resolved
    assert "\\n" not in resolved
    assert "@@ -1 +1 @@" in resolved


def test_maybe_unescape_unified_diff_leaves_non_diff_text() -> None:
    raw = "hello\\nworld"
    assert workspace._maybe_unescape_unified_diff(raw) == raw


def test_maybe_unescape_unified_diff_leaves_multiline_diff() -> None:
    raw = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n"
    assert workspace._maybe_unescape_unified_diff(raw) == raw

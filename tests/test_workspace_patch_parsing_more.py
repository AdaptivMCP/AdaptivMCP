import os

import pytest

from github_mcp.exceptions import GitHubAPIError
from github_mcp import workspace


def test_parse_rangeless_git_patch_parses_update_and_move_to() -> None:
    patch = """\
diff --git a/foo.txt b/bar.txt
index 0000000..1111111 100644
--- a/foo.txt
+++ b/bar.txt
@@
 one
-two
+TWO
@@
 three
"""

    blocks = workspace._parse_rangeless_git_patch(patch)
    assert len(blocks) == 1
    b0 = blocks[0]
    assert b0["action"] == "update"
    assert b0["path"] == "foo.txt"
    assert b0["move_to"] == "bar.txt"
    assert b0["hunks"] == [[" one", "-two", "+TWO"], [" three"]]


def test_parse_rangeless_git_patch_rejects_blank_line_without_prefix() -> None:
    patch = """\
diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@

"""
    with pytest.raises(GitHubAPIError, match="blank line without diff prefix"):
        workspace._parse_rangeless_git_patch(patch)


def test_safe_repo_path_rejects_absolute_and_drive_qualified(tmp_path) -> None:
    repo_dir = str(tmp_path)

    with pytest.raises(GitHubAPIError, match="repository-relative"):
        workspace._safe_repo_path(repo_dir, "/etc/passwd")

    with pytest.raises(GitHubAPIError, match="repository-relative"):
        workspace._safe_repo_path(repo_dir, "C:/Windows/System32")


def test_safe_repo_path_prevents_escape(tmp_path) -> None:
    repo_dir = str(tmp_path)
    with pytest.raises(GitHubAPIError, match="repository-relative"):
        workspace._safe_repo_path(repo_dir, "../secrets.txt")


def test_apply_rangeless_git_patch_updates_and_renames_file(tmp_path) -> None:
    repo_dir = str(tmp_path)
    a_path = tmp_path / "foo.txt"
    a_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    patch = """\
diff --git a/foo.txt b/bar.txt
--- a/foo.txt
+++ b/bar.txt
@@
 one
-two
+TWO
@@
 three
"""

    workspace._apply_rangeless_git_patch(repo_dir, patch)

    assert not os.path.exists(str(a_path))
    b_path = tmp_path / "bar.txt"
    assert b_path.exists()
    assert b_path.read_text(encoding="utf-8") == "one\nTWO\nthree\n"

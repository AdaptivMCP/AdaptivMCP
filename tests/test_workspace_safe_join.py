import os


def test_workspace_safe_join_accepts_absolute_path_inside_repo(tmp_path):
    from github_mcp.workspace_tools import fs

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    target = repo_dir / "a" / "b.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hello", encoding="utf-8")

    abs_path = os.path.realpath(str(target))
    resolved = fs._workspace_safe_join(str(repo_dir), abs_path)
    assert os.path.realpath(resolved) == abs_path


def test_workspace_safe_join_rejects_absolute_path_outside_repo(tmp_path):
    from github_mcp.workspace_tools import fs

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    abs_outside = os.path.realpath(str(outside))
    try:
        fs._workspace_safe_join(str(repo_dir), abs_outside)
    except ValueError as exc:
        assert "inside the workspace repository" in str(exc) or "repository-relative" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_workspace_safe_join_treats_empty_path_as_repo_root(tmp_path):
    from github_mcp.workspace_tools import fs

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    resolved = fs._workspace_safe_join(str(repo_dir), "")
    assert os.path.realpath(resolved) == os.path.realpath(str(repo_dir))

    resolved = fs._workspace_safe_join(str(repo_dir), "   ")
    assert os.path.realpath(resolved) == os.path.realpath(str(repo_dir))


def test_workspace_safe_join_clamps_parent_directory_segments(tmp_path):
    """Regression: callers often send ../ paths; we should clamp safely."""

    from github_mcp.workspace_tools import fs

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "usage.md").write_text("ok", encoding="utf-8")

    # Previously this could hard-fail; now it clamps back into the repo.
    resolved = fs._workspace_safe_join(str(repo_dir), "../docs/usage.md")
    assert os.path.realpath(resolved) == os.path.realpath(str(repo_dir / "docs" / "usage.md"))

    # Traversal beyond root should clamp to root, not escape.
    resolved_root = fs._workspace_safe_join(str(repo_dir), "../../../")
    assert os.path.realpath(resolved_root) == os.path.realpath(str(repo_dir))

    # Parent segments in the middle should normalize.
    (repo_dir / "a").mkdir()
    (repo_dir / "a" / "b.txt").write_text("hi", encoding="utf-8")
    resolved = fs._workspace_safe_join(str(repo_dir), "docs/../a/b.txt")
    assert os.path.realpath(resolved) == os.path.realpath(str(repo_dir / "a" / "b.txt"))


def test_workspace_safe_join_collapses_dot_paths_to_root(tmp_path):
    from github_mcp.workspace_tools import fs

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    for p in (".", "./", "/", "..", "../", "./../"):
        resolved = fs._workspace_safe_join(str(repo_dir), p)
        assert os.path.realpath(resolved) == os.path.realpath(str(repo_dir))

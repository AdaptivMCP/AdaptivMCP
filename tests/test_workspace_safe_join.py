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
        assert "inside the workspace repository" in str(
            exc
        ) or "repository-relative" in str(exc)
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

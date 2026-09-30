from __future__ import annotations

import os

import pytest


def test_default_workdir_is_repo_root(tmp_path):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    repo.mkdir()

    assert _resolve_workdir(str(repo), None) == os.path.realpath(repo)


def test_relative_workdir_inside_repo_allowed(tmp_path):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)

    assert _resolve_workdir(str(repo), "src/pkg") == os.path.realpath(nested)


def test_absolute_workdir_inside_repo_allowed(tmp_path):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    nested = repo / "src"
    nested.mkdir(parents=True)

    assert _resolve_workdir(str(repo), str(nested)) == os.path.realpath(nested)


@pytest.mark.parametrize("workdir", ["..", "../outside", "/tmp"])
def test_external_workdir_rejected(tmp_path, workdir):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="inside the repository workspace"):
        _resolve_workdir(str(repo), workdir)


def test_symlink_to_external_directory_rejected(tmp_path):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="inside the repository workspace"):
        _resolve_workdir(str(repo), "escape")


def test_symlink_to_external_directory_with_nested_path_rejected(tmp_path):
    from github_mcp.workspace_tools.commands import _resolve_workdir

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    nested = outside / "nested"
    nested.mkdir(parents=True)
    (repo / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="inside the repository workspace"):
        _resolve_workdir(str(repo), "escape/nested")

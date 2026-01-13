import asyncio

from github_mcp.workspace_tools import listing as workspace_listing


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _resolve_full_name(self, full_name, owner=None, repo=None):
        return full_name or "octo/example"

    def _resolve_ref(self, ref, branch=None):
        return branch or ref

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_list_workspace_files_allows_path_escape(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sibling = tmp_path / "repo-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = asyncio.run(workspace_listing.list_workspace_files(path="../repo-sibling"))

    assert "error" not in result
    assert "../repo-sibling/secret.txt" in result["files"]


def test_list_workspace_files_allows_absolute_path_inside_repo(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    target = repo_dir / "docs" / "readme.md"
    target.parent.mkdir()
    target.write_text("ok")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = asyncio.run(workspace_listing.list_workspace_files(path=str(target)))

    assert "error" not in result
    assert result["files"] == ["docs/readme.md"]
    assert result["path"] == "docs/readme.md"


def test_list_workspace_files_allows_absolute_path_outside_repo(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = asyncio.run(workspace_listing.list_workspace_files(path=str(target)))

    assert "error" not in result
    assert "../outside/secret.txt" in result["files"]


def test_search_workspace_allows_path_escape(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sibling = tmp_path / "repo-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_listing.search_workspace(
            query="nope",
            path="../repo-sibling/secret.txt",
        )
    )

    assert "error" not in result
    assert result["results"]
    assert result["results"][0]["file"] == "../repo-sibling/secret.txt"


def test_search_workspace_allows_absolute_path_outside_repo(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_listing.search_workspace(
            query="nope",
            path=str(target),
        )
    )

    assert "error" not in result
    assert result["results"]
    assert result["results"][0]["file"] == "../outside/secret.txt"

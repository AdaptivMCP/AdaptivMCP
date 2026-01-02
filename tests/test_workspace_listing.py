import pytest

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


@pytest.mark.asyncio
async def test_list_workspace_files_blocks_path_escape(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sibling = tmp_path / "repo-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = await workspace_listing.list_workspace_files(path="../repo-sibling")

    assert "error" in result
    assert result["error"]["message"] == "path must stay within repo"


@pytest.mark.asyncio
async def test_search_workspace_blocks_path_escape(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    sibling = tmp_path / "repo-sibling"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    result = await workspace_listing.search_workspace(
        query="nope",
        path="../repo-sibling/secret.txt",
    )

    assert "error" in result
    assert result["error"]["message"] == "path must stay within repo"

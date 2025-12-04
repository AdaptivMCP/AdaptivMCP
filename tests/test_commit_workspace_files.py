import subprocess

import pytest

import main


@pytest.mark.asyncio
async def test_commit_workspace_files_stages_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo_dir, check=True)

    (repo_dir / "file1.txt").write_text("one\n", encoding="utf-8")
    (repo_dir / "file2.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "add", "file1.txt", "file2.txt"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True)

    (repo_dir / "file1.txt").write_text("one updated\n", encoding="utf-8")
    (repo_dir / "file2.txt").write_text("two updated\n", encoding="utf-8")

    async def fake_clone(
        full_name: str, ref: str | None = None, *, preserve_changes: bool = False
    ) -> str:
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    result = await main.commit_workspace_files(
        full_name="owner/repo",
        files=["file1.txt"],
        ref="main",
        message="selective commit",
        push=False,
    )

    assert "error" not in result
    last_commit_files = subprocess.check_output(
        ["git", "show", "--name-only", "--pretty=format:"], cwd=repo_dir
    ).decode("utf-8")
    assert "file1.txt" in last_commit_files
    assert "file2.txt" not in last_commit_files

    status_output = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_dir)
    assert any(line.startswith(" M file2.txt") for line in status_output.decode("utf-8").splitlines())


@pytest.mark.asyncio
async def test_commit_workspace_files_requires_files(monkeypatch):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(ValueError):
        await main.commit_workspace_files("owner/repo", files=[], push=False)

import subprocess
import textwrap

import pytest

import main


@pytest.mark.asyncio
async def test_apply_patch_and_open_pr_detects_empty_diff(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    (repo_dir / "sample.txt").write_text("same\n", encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=repo_dir, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            "init",
            "--quiet",
        ],
        cwd=repo_dir,
        check=True,
    )

    async def fake_clone(full_name: str, ref: str = "main") -> str:  # noqa: ARG001
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    patch = textwrap.dedent(
        """
        --- a/sample.txt
        +++ b/sample.txt
        @@ -1 +1 @@
        -same
        +same
        """
    )

    result = await main.apply_patch_and_open_pr(
        full_name="owner/repo",
        base_branch="main",
        patch=patch,
        title="Test empty diff",
    )

    assert result["error"] == "empty_diff"
    assert "no changes" in result["stderr"]


@pytest.mark.asyncio
async def test_apply_patch_and_open_pr_surfaces_apply_errors(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    (repo_dir / "existing.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "existing.txt"], cwd=repo_dir, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            "init",
            "--quiet",
        ],
        cwd=repo_dir,
        check=True,
    )

    async def fake_clone(full_name: str, ref: str = "main") -> str:  # noqa: ARG001
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    patch = textwrap.dedent(
        """
        --- a/missing.txt
        +++ b/missing.txt
        @@ -1 +1 @@
        -hello
        +hello world
        """
    )

    result = await main.apply_patch_and_open_pr(
        full_name="owner/repo",
        base_branch="main",
        patch=patch,
        title="Test apply failure",
    )

    assert result["error"] == "git_apply_failed"
    assert "git apply --check failed" in result["stderr"]
    assert "missing.txt" in result["stderr"]
    assert "Patch with line numbers" in result["stderr"]

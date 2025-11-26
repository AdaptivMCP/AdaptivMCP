import subprocess
import textwrap

import pytest

import main


@pytest.mark.asyncio
async def test_run_command_applies_patch_before_command(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    (repo_dir / "sample.txt").write_text("old\n", encoding="utf-8")
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
        ],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def fake_clone(full_name: str, ref: str = "main") -> str:
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    patch = textwrap.dedent(
        """
        --- a/sample.txt
        +++ b/sample.txt
        @@ -1 +1 @@
        -old
        +new
        """
    )

    result = await main.run_command(
        full_name="owner/repo",
        ref="main",
        command="cat sample.txt",
        patch=patch,
    )

    assert result["result"]["exit_code"] == 0
    assert result["result"]["stdout"].strip() == "new"


@pytest.mark.asyncio
async def test_run_shell_flags_truncation(monkeypatch):
    monkeypatch.setattr(main, "TOOL_STDOUT_MAX_CHARS", 18)
    monkeypatch.setattr(main, "TOOL_STDERR_MAX_CHARS", 16)

    cmd = "python - <<'PY'\nimport sys\nsys.stdout.write('A' * 20)\nsys.stderr.write('B' * 30)\nPY"
    result = await main._run_shell(cmd)

    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert len(result["stdout"]) <= main.TOOL_STDOUT_MAX_CHARS
    assert len(result["stderr"]) <= main.TOOL_STDERR_MAX_CHARS
    assert result["stdout"].endswith("[truncated]")
    assert result["stderr"].endswith("[truncated]")

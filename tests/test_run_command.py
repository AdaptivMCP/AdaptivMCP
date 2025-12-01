import subprocess
import os
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
async def test_run_shell_returns_full_output():
    cmd = "python - <<'PY'\nimport sys\nsys.stdout.write('A' * 20)\nsys.stderr.write('B' * 30)\nPY"
    result = await main._run_shell(cmd)

    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False
    assert result["stdout"] == "A" * 20
    assert result["stderr"] == "B" * 30


@pytest.mark.asyncio
async def test_run_command_uses_temp_virtualenv(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def fake_clone(*_, **__):
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    calls = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)

    await main.run_command(full_name="owner/repo", command="echo ok")

    assert any("-m venv" in call["cmd"] for call in calls)
    run_call = calls[-1]
    assert run_call["env"] is not None

    venv_path = run_call["env"]["VIRTUAL_ENV"]
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    expected_prefix = os.path.join(venv_path, bin_dir)
    assert run_call["env"]["PATH"].startswith(expected_prefix)


@pytest.mark.asyncio
async def test_run_command_allows_disabling_virtualenv(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def fake_clone(*_, **__):
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    calls = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append({"cmd": cmd, "cwd": cwd, "env": env})
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)

    await main.run_command(
        full_name="owner/repo", command="echo ok", use_temp_venv=False
    )

    assert not any("-m venv" in call["cmd"] for call in calls)
    assert calls[-1]["env"] is None


@pytest.mark.asyncio
async def test_run_shell_truncates_output_when_limits_exceeded(monkeypatch):
    """When TOOL_STDOUT_MAX_CHARS / TOOL_STDERR_MAX_CHARS are small,
    _run_shell should truncate output and set the truncation flags.
    """

    monkeypatch.setattr(main, "TOOL_STDOUT_MAX_CHARS", 10)
    monkeypatch.setattr(main, "TOOL_STDERR_MAX_CHARS", 5)

    cmd = (
        "python - <<'PY'\n"
        "import sys\n"
        "sys.stdout.write('A' * 20)\n"
        "sys.stderr.write('B' * 30)\n"
        "PY"
    )
    result = await main._run_shell(cmd)

    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert result["stdout"] == "A" * 10
    assert result["stderr"] == "B" * 5


@pytest.mark.asyncio
async def test_run_shell_no_truncation_when_limits_disabled(monkeypatch):
    """If the truncation limits are disabled (0 or negative), _run_shell
    should return full output and leave truncation flags False.
    """

    monkeypatch.setattr(main, "TOOL_STDOUT_MAX_CHARS", 0)
    monkeypatch.setattr(main, "TOOL_STDERR_MAX_CHARS", -1)

    cmd = (
        "python - <<'PY'\n"
        "import sys\n"
        "sys.stdout.write('A' * 20)\n"
        "sys.stderr.write('B' * 30)\n"
        "PY"
    )
    result = await main._run_shell(cmd)

    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False
    assert result["stdout"] == "A" * 20
    assert result["stderr"] == "B" * 30


@pytest.mark.asyncio
async def test_clone_repo_reuses_persistent_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    workspace_root = tmp_path / "workspaces"
    monkeypatch.setattr(main, "WORKSPACE_BASE_DIR", str(workspace_root))

    repo_dir = workspace_root / "owner__repo" / "main"
    repo_dir.mkdir(parents=True)
    (repo_dir / ".git").mkdir()

    calls: list[str] = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append(cmd)
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)

    result = await main.run_command(
        full_name="owner/repo",
        ref="main",
        command="echo ok",
        use_temp_venv=False,
    )

    assert result["repo_dir"] == str(repo_dir)
    assert any(cmd == "echo ok" for cmd in calls)
    assert not any(cmd.startswith("git clone") for cmd in calls)


@pytest.mark.asyncio
async def test_commit_workspace_creates_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo_dir,
        check=True,
    )

    (repo_dir / "sample.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    (repo_dir / "sample.txt").write_text("updated\n", encoding="utf-8")

    async def fake_clone(full_name: str, ref: str | None = None) -> str:
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    result = await main.commit_workspace(
        full_name="owner/repo", ref="main", message="test commit", push=False
    )

    assert "error" not in result
    log_output = subprocess.check_output(
        ["git", "log", "-1", "--pretty=%B"], cwd=repo_dir
    ).decode("utf-8")
    assert "test commit" in log_output

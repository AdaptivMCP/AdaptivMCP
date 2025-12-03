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

    async def fake_clone(
        full_name: str, ref: str = "main", *, preserve_changes: bool = False
    ) -> str:
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
async def test_run_command_read_only_skips_write_gate(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def fake_clone(*_, **__):
        return str(repo_dir)

    async def fake_prepare_temp_virtualenv(repo_path: str):  # type: ignore[override]
        assert repo_path == str(repo_dir)
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

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

    def fail_write_gate(context: str) -> None:  # pragma: no cover - should not fire
        raise AssertionError(f"write gate should not run for read commands: {context}")

    monkeypatch.setattr(main, "_clone_repo", fake_clone)
    monkeypatch.setattr(main, "_prepare_temp_virtualenv", fake_prepare_temp_virtualenv)
    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    monkeypatch.setattr(main, "_ensure_write_allowed", fail_write_gate)

    result = await main.run_command(full_name="owner/repo", command="echo ok")

    assert result["result"]["exit_code"] == 0
    assert calls[-1] == "echo ok"


@pytest.mark.asyncio
async def test_run_command_mutating_triggers_write_gate(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def fake_clone(*_, **__):
        return str(repo_dir)

    async def fake_prepare_temp_virtualenv(repo_path: str):  # type: ignore[override]
        assert repo_path == str(repo_dir)
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    write_contexts: list[str] = []

    def record_write_gate(context: str) -> None:
        write_contexts.append(context)

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(main, "_clone_repo", fake_clone)
    monkeypatch.setattr(main, "_prepare_temp_virtualenv", fake_prepare_temp_virtualenv)
    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    monkeypatch.setattr(main, "_ensure_write_allowed", record_write_gate)

    result = await main.run_command(
        full_name="owner/repo", command="echo ok", mutating=True
    )

    assert result["result"]["exit_code"] == 0
    assert write_contexts and "run_command" in write_contexts[-1]


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
async def test_run_shell_combined_truncation(monkeypatch):
    """A combined cap keeps stdout+stderr under the configured budget."""

    monkeypatch.setattr(main, "TOOL_STDOUT_MAX_CHARS", 100)
    monkeypatch.setattr(main, "TOOL_STDERR_MAX_CHARS", 100)
    monkeypatch.setattr(main, "TOOL_STDIO_COMBINED_MAX_CHARS", 50)

    cmd = (
        "python - <<'PY'\n"
        "import sys\n"
        "sys.stdout.write('A' * 40)\n"
        "sys.stderr.write('B' * 40)\n"
        "PY"
    )
    result = await main._run_shell(cmd)

    assert len(result["stdout"]) + len(result["stderr"]) <= 50
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True or len(result["stderr"]) == 40
    assert result["stdout"].startswith("A")
    assert result["stderr"].startswith("B")


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

    calls: list[tuple[str, str | None]] = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append((cmd, cwd))
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
    assert calls[0] == ("git fetch origin --prune", str(repo_dir))
    assert any(cmd == ("echo ok", str(repo_dir)) for cmd in calls)
    assert not any(cmd.startswith("git reset") for cmd, _ in calls)
    assert not any(cmd.startswith("git clean") for cmd, _ in calls)


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

    async def fake_clone(
        full_name: str, ref: str | None = None, *, preserve_changes: bool = False
    ) -> str:
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


@pytest.mark.asyncio
async def test_run_command_and_commit_share_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    clone_calls: list[bool] = []
    async def fake_clone(
        full_name: str, ref: str | None = None, *, preserve_changes: bool = False
    ) -> str:
        clone_calls.append(preserve_changes)
        return str(repo_dir)

    monkeypatch.setattr(main, "_clone_repo", fake_clone)

    shell_commands: list[str] = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        shell_commands.append(cmd)
        if cmd.startswith("git status --porcelain"):
            return {
                "exit_code": 0,
                "timed_out": False,
                "stdout": " M sample.txt\n",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            }

        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)

    run_result = await main.run_command(
        full_name="owner/repo",
        ref="feature",
        command="echo hi",
        use_temp_venv=False,
    )

    commit_result = await main.commit_workspace(
        full_name="owner/repo",
        ref="feature",
        message="msg",
        push=False,
    )

    assert run_result["repo_dir"] == str(repo_dir)
    assert commit_result["repo_dir"] == str(repo_dir)
    assert clone_calls == [True, True]
    assert "git add -A" in shell_commands
    assert any(cmd.startswith("git commit") for cmd in shell_commands)

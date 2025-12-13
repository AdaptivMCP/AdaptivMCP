import pytest


@pytest.mark.asyncio
async def test_run_command_adds_dependency_hint_on_module_not_found(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_prepare_temp_virtualenv(repo_dir):
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    calls = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append(cmd)
        return {
            "exit_code": 1,
            "timed_out": False,
            "stdout": "",
            "stderr": "Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'jsonschema'\n",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    def fake_ensure_write_allowed(context):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "prepare_temp_virtualenv": fake_prepare_temp_virtualenv,
            "run_shell": fake_run_shell,
            "ensure_write_allowed": fake_ensure_write_allowed,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    res = await tw.run_command(
        full_name="owner/repo", ref="main", command="python -c 'x'", use_temp_venv=True
    )

    assert res["result"]["exit_code"] == 1
    assert res["dependency_hint"]["missing_module"] == "jsonschema"
    assert "installing_dependencies=true" in res["dependency_hint"]["message"]
    assert res["install"] is None
    assert calls[-1] == "python -c 'x'"


@pytest.mark.asyncio
async def test_run_command_installs_requirements_when_requested(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_prepare_temp_virtualenv(repo_dir):
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    calls = []

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

    def fake_ensure_write_allowed(context):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "prepare_temp_virtualenv": fake_prepare_temp_virtualenv,
            "run_shell": fake_run_shell,
            "ensure_write_allowed": fake_ensure_write_allowed,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    res = await tw.run_command(
        full_name="owner/repo",
        ref="main",
        command="pytest -q",
        installing_dependencies=True,
        use_temp_venv=True,
    )

    assert res["result"]["exit_code"] == 0
    assert calls[0] == "python -m pip install -r requirements.txt"
    assert calls[1] == "pytest -q"


@pytest.mark.asyncio
async def test_run_command_skips_auto_install_if_command_installs(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_prepare_temp_virtualenv(repo_dir):
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    calls = []

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

    def fake_ensure_write_allowed(context):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "prepare_temp_virtualenv": fake_prepare_temp_virtualenv,
            "run_shell": fake_run_shell,
            "ensure_write_allowed": fake_ensure_write_allowed,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    cmd = "python -m pip install -r requirements.txt && pytest -q"
    res = await tw.run_command(
        full_name="owner/repo",
        ref="main",
        command=cmd,
        installing_dependencies=True,
        use_temp_venv=True,
    )

    assert res["result"]["exit_code"] == 0
    assert calls == [cmd]

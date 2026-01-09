import asyncio


def test_terminal_command_auto_installs_for_python_commands(monkeypatch):
    """Ensure terminal_command installs deps automatically for python-centric commands."""

    from github_mcp.workspace_tools import commands

    repo_dir = "/tmp/repo"

    calls = {"prepare_venv": 0, "install": 0, "run": 0}

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return repo_dir

    async def fake_prepare_temp_virtualenv(_repo_dir):
        calls["prepare_venv"] += 1
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=0, env=None):
        if "pip install -r" in cmd:
            calls["install"] += 1
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}
        calls["run"] += 1
        return {"exit_code": 0, "stdout": "hello", "stderr": ""}

    class FakeTW:
        def _workspace_deps(self):
            return {
                "clone_repo": fake_clone_repo,
                "prepare_temp_virtualenv": fake_prepare_temp_virtualenv,
                "run_shell": fake_run_shell,
            }

        def _resolve_full_name(self, full_name=None, owner=None, repo=None):
            return full_name or "org/repo"

        def _resolve_ref(self, ref, branch=None):
            return ref

        def _effective_ref_for_repo(self, full_name, ref):
            return ref

    # Avoid filesystem checks for requirements files.
    monkeypatch.setattr(commands, "_tw", lambda: FakeTW())
    monkeypatch.setattr(commands.os.path, "exists", lambda p: True)

    # Run a python-centric command; should auto-install.
    out = asyncio.run(
        commands.terminal_command(
            full_name="org/repo", command="python -c 'print(1)'", use_temp_venv=True
        )
    )

    assert out["result"]["exit_code"] == 0
    assert calls["prepare_venv"] == 1
    assert calls["install"] == 1
    assert calls["run"] == 1


def test_terminal_command_does_not_auto_install_for_non_python_commands(monkeypatch):
    """Non-python commands should not trigger pip installs by default."""

    from github_mcp.workspace_tools import commands

    repo_dir = "/tmp/repo"

    calls = {"prepare_venv": 0, "install": 0, "run": 0}

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return repo_dir

    async def fake_prepare_temp_virtualenv(_repo_dir):
        calls["prepare_venv"] += 1
        return {"VIRTUAL_ENV": "/tmp/venv", "PATH": "/tmp/venv/bin"}

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=0, env=None):
        if "pip install -r" in cmd:
            calls["install"] += 1
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}
        calls["run"] += 1
        return {"exit_code": 0, "stdout": "non-python-ok", "stderr": ""}

    class FakeTW:
        def _workspace_deps(self):
            return {
                "clone_repo": fake_clone_repo,
                "prepare_temp_virtualenv": fake_prepare_temp_virtualenv,
                "run_shell": fake_run_shell,
            }

        def _resolve_full_name(self, full_name=None, owner=None, repo=None):
            return full_name or "org/repo"

        def _resolve_ref(self, ref, branch=None):
            return ref

        def _effective_ref_for_repo(self, full_name, ref):
            return ref

    monkeypatch.setattr(commands, "_tw", lambda: FakeTW())
    monkeypatch.setattr(commands.os.path, "exists", lambda p: True)

    out = asyncio.run(
        commands.terminal_command(
            full_name="org/repo", command="echo non-python-ok", use_temp_venv=True
        )
    )

    assert out["result"]["exit_code"] == 0
    assert calls["prepare_venv"] == 1
    assert calls["install"] == 0
    assert calls["run"] == 1

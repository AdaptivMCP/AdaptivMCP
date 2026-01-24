from __future__ import annotations

import os
import shlex
from types import SimpleNamespace

import pytest


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!stub\n")


@pytest.mark.anyio
async def test_prepare_virtualenv_creates_marker_and_is_reused(monkeypatch, tmp_path):
    import github_mcp.workspace as workspace

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    calls: list[str] = []

    async def fake_run_shell(cmd: str, *, cwd=None, timeout_seconds=0, env=None):
        calls.append(cmd)

        # Simulate venv creation by creating python executables.
        if " -m venv" in cmd:
            parts = shlex.split(cmd)
            venv_root = parts[-1]
            _touch(os.path.join(venv_root, "bin", "python"))
            _touch(os.path.join(venv_root, "Scripts", "python.exe"))
            return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

        # Simulate pip/ensurepip.
        if "-m pip" in cmd or "-m ensurepip" in cmd:
            return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    dummy_main = SimpleNamespace(_run_shell=fake_run_shell)

    # Force workspace helpers to use our fake shell.
    monkeypatch.setattr(workspace, "_get_main_module", lambda: dummy_main)

    env1 = await workspace._prepare_temp_virtualenv(str(repo_dir))

    venv_dir = os.path.join(str(repo_dir), ".venv-mcp")
    assert env1["VIRTUAL_ENV"] == venv_dir
    assert os.path.isdir(venv_dir)

    # Ensure the marker is written and python exists.
    assert os.path.isfile(os.path.join(venv_dir, ".mcp_ready"))
    assert os.path.isfile(os.path.join(venv_dir, "bin", "python")) or os.path.isfile(
        os.path.join(venv_dir, "Scripts", "python.exe")
    )

    calls_after_first = list(calls)

    # Second call should use the ready marker fast-path and not invoke run_shell.
    env2 = await workspace._prepare_temp_virtualenv(str(repo_dir))
    assert env2["VIRTUAL_ENV"] == venv_dir
    assert calls == calls_after_first


@pytest.mark.anyio
async def test_stop_virtualenv_removes_directory(monkeypatch, tmp_path):
    import github_mcp.workspace as workspace

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    venv_dir = repo_dir / ".venv-mcp"
    venv_dir.mkdir(parents=True)
    _touch(str(venv_dir / "bin" / "python"))

    # No shell needed for stop, but we still provide a dummy main.
    dummy_main = SimpleNamespace(_run_shell=lambda *a, **k: None)
    monkeypatch.setattr(workspace, "_get_main_module", lambda: dummy_main)

    status_before = await workspace._workspace_virtualenv_status(str(repo_dir))
    assert status_before["exists"] is True

    stopped = await workspace._stop_workspace_virtualenv(str(repo_dir))
    assert stopped["existed"] is True
    assert os.path.isdir(venv_dir) is False

    status_after = await workspace._workspace_virtualenv_status(str(repo_dir))
    assert status_after["exists"] is False
    assert status_after["ready"] is False


@pytest.mark.anyio
async def test_workspace_venv_tools_skip_install_when_missing_requirements(
    monkeypatch, tmp_path
):
    import github_mcp.workspace_tools.venv as venv_tools

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    calls: list[tuple[str, str]] = []

    async def clone_repo(_full_name: str, *, ref: str, preserve_changes: bool):
        assert preserve_changes is True
        return str(repo_dir)

    async def prepare_venv(_repo_dir: str):
        return {"VIRTUAL_ENV": os.path.join(str(repo_dir), ".venv-mcp"), "PATH": ""}

    async def run_shell(cmd: str, *, cwd: str, timeout_seconds: int, env=None):
        calls.append((cmd, cwd))
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    async def venv_status(_repo_dir: str):
        return {"exists": True, "ready": True}

    async def stop_venv(_repo_dir: str):
        return {"existed": False, "deleted": True}

    fake_tw = SimpleNamespace(
        _effective_ref_for_repo=lambda full_name, ref: ref,
        _workspace_deps=lambda: {
            "clone_repo": clone_repo,
            "prepare_temp_virtualenv": prepare_venv,
            "run_shell": run_shell,
            "virtualenv_status": venv_status,
            "stop_virtualenv": stop_venv,
        },
    )

    monkeypatch.setattr(venv_tools, "_tw", lambda: fake_tw)

    out = await venv_tools.workspace_venv_start(
        full_name="owner/repo", ref="main", installing_dependencies=True
    )

    assert out["ref"] == "main"
    assert out["install_log"]["skipped"] is True
    assert calls == []

    out2 = await venv_tools.workspace_venv_stop(full_name="owner/repo", ref="main")
    assert out2["ref"] == "main"
    assert out2["stopped"]["deleted"] is True

    out3 = await venv_tools.workspace_venv_status(full_name="owner/repo", ref="main")
    assert out3["ref"] == "main"
    assert out3["venv"]["ready"] is True

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

import github_mcp.workspace_tools.commands as cmds


class _StubTW:
    def __init__(self, deps: Dict[str, Any]):
        self._deps = deps

    def _workspace_deps(self) -> Dict[str, Any]:
        return self._deps

    def _resolve_full_name(
        self, full_name: Optional[str], *, owner: Optional[str], repo: Optional[str]
    ) -> str:
        return full_name or f"{owner}/{repo}"  # type: ignore[return-value]

    def _resolve_ref(self, ref: str, *, branch: Optional[str]) -> str:
        return branch or ref

    def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:
        return ref


@pytest.mark.asyncio
async def test_terminal_command_refreshes_tree_when_not_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    async def clone_repo(full_name: str, *, ref: str, preserve_changes: bool) -> str:
        captured["full_name"] = full_name
        captured["ref"] = ref
        captured["preserve_changes"] = preserve_changes
        return "/tmp/repo"

    async def prepare_temp_virtualenv(repo_dir: str) -> Dict[str, str]:
        return {"VIRTUAL_ENV": "/tmp/venv"}

    async def run_shell(
        command: str, *, cwd: str, timeout_seconds: int, env: Dict[str, str] | None
    ) -> Dict[str, Any]:
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    deps = {
        "clone_repo": clone_repo,
        "prepare_temp_virtualenv": prepare_temp_virtualenv,
        "run_shell": run_shell,
        "ensure_write_allowed": lambda *a, **k: None,
    }

    monkeypatch.setattr(cmds, "_tw", lambda: _StubTW(deps))

    out = await cmds.terminal_command(
        full_name="owner/repo",
        ref="main",
        command="python -c 'print(1)'",
        use_temp_venv=True,
        installing_dependencies=False,
        mutating=False,
    )

    assert out["repo_dir"] == "/tmp/repo"
    assert captured["preserve_changes"] is False


@pytest.mark.asyncio
async def test_terminal_command_preserves_tree_when_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {"ensure_called": False}

    async def clone_repo(full_name: str, *, ref: str, preserve_changes: bool) -> str:
        captured["preserve_changes"] = preserve_changes
        return "/tmp/repo"

    async def prepare_temp_virtualenv(repo_dir: str) -> Dict[str, str]:
        return {"VIRTUAL_ENV": "/tmp/venv"}

    async def run_shell(
        command: str, *, cwd: str, timeout_seconds: int, env: Dict[str, str] | None
    ) -> Dict[str, Any]:
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    def ensure_write_allowed(*args: Any, **kwargs: Any) -> None:
        captured["ensure_called"] = True

    deps = {
        "clone_repo": clone_repo,
        "prepare_temp_virtualenv": prepare_temp_virtualenv,
        "run_shell": run_shell,
        "ensure_write_allowed": ensure_write_allowed,
    }

    monkeypatch.setattr(cmds, "_tw", lambda: _StubTW(deps))

    out = await cmds.terminal_command(
        full_name="owner/repo",
        ref="main",
        command="python -c 'print(2)'",
        use_temp_venv=True,
        installing_dependencies=False,
        mutating=True,
    )

    assert out["repo_dir"] == "/tmp/repo"
    assert captured["ensure_called"] is True
    assert captured["preserve_changes"] is True

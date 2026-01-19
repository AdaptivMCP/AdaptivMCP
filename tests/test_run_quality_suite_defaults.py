from __future__ import annotations

import types

import pytest


@pytest.mark.anyio
async def test_run_quality_suite_defaults_use_temp_venv_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_quality_suite should default to an isolated temp venv.

    This keeps the suite deterministic across provider environments and ensures
    `installing_dependencies=True` can take effect.
    """

    from github_mcp.workspace_tools import suites

    calls: list[dict] = []

    async def _fake_terminal_command(*args, **kwargs):
        calls.append(dict(kwargs))
        return {
            "command_input": kwargs.get("command"),
            "command": kwargs.get("command"),
            "result": {
                "exit_code": 0,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            },
        }

    fake_tw = types.SimpleNamespace(terminal_command=_fake_terminal_command)
    monkeypatch.setattr(suites, "_tw", lambda: fake_tw)

    out = await suites.run_quality_suite(
        full_name="OWNER/REPO",
        ref="main",
        # Ensure the suite is exercising its defaulting logic.
        installing_dependencies=True,
    )

    assert out.get("status") == "passed"

    suite = out.get("suite") or {}
    commands = suite.get("commands") or {}
    assert commands.get("typecheck") == "mypy ."
    security_cmd = str(commands.get("security") or "")
    assert "pip-audit" in security_cmd
    assert "bandit" in security_cmd

    assert calls, "expected run_quality_suite to invoke terminal_command"

    # Every terminal_command call should receive use_temp_venv=True by default.
    assert all(call.get("use_temp_venv") is True for call in calls)

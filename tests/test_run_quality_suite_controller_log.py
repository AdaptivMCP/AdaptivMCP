from __future__ import annotations

import types

import pytest


@pytest.mark.asyncio
async def test_run_quality_suite_merges_controller_log_on_lint_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: fail-fast lint path must return suite UI/log.

    The suite should return a stable payload plus a UI summary and must not rely
    on nested tool UI fields.
    """

    from github_mcp.workspace_tools import suites

    async def _fake_terminal_command(*args, **kwargs):
        # Simulate terminal_command payload shape.
        return {
            "command_input": kwargs.get("command"),
            "command": kwargs.get("command"),
            "result": {
                "exit_code": 1,
                "timed_out": False,
                "stdout": "",
                "stderr": "boom\n",
                "stdout_truncated": False,
                "stderr_truncated": False,
            },
            "controller_log": [
                "Command: fake",
                "Exit code: 1",
            ],
        }

    fake_tw = types.SimpleNamespace(terminal_command=_fake_terminal_command)
    monkeypatch.setattr(suites, "_tw", lambda: fake_tw)

    out = await suites.run_quality_suite(
        full_name="OWNER/REPO",
        ref="main",
        lint_command="fake lint",
        test_command="pytest",
        fail_fast=True,
        use_temp_venv=True,
        installing_dependencies=False,
    )

    assert isinstance(out, dict)
    assert out.get("status") == "failed"
    assert "suite" in out
    assert "steps" in out

    ui = out.get("ui")
    assert isinstance(ui, dict)
    log = ui.get("bullets")
    assert isinstance(log, list)

    # Suite log must be present and must end with the abort marker.
    assert log[0] == "Quality suite run:"
    assert any(line == "- Lint: failed" for line in log)

    # Aborted marker must be appended.
    assert log[-1] == "- Aborted: lint failed"

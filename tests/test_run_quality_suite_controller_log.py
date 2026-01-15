from __future__ import annotations

import types

import pytest


@pytest.mark.anyio
async def test_run_quality_suite_controller_log_on_lint_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-fast lint failures must return a complete suite controller_log.

    The suite returns a stable top-level payload and keeps the underlying
    terminal_command payload on the step under steps[*].raw.
    """

    from github_mcp.workspace_tools import suites

    async def _fake_terminal_command(*args, **kwargs):
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
            "controller_log": ["Command: fake", "Exit code: 1"],
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
        include_raw_step_outputs=True,
    )

    assert isinstance(out, dict)
    assert out.get("status") == "failed"
    assert "suite" in out
    assert "steps" in out

    log = out.get("controller_log")
    assert isinstance(log, list)

    assert any(line == "Quality suite run:" for line in log)
    assert any(line == "- Repo: OWNER/REPO" for line in log)
    assert any(line == "- Ref: main" for line in log)
    assert log[-1] == "- Aborted: lint failed"

    steps = out.get("steps")
    assert isinstance(steps, list)

    lint_step = next(step for step in steps if step.get("name") == "lint")
    raw = lint_step.get("raw")
    assert isinstance(raw, dict)
    assert raw.get("controller_log") == ["Command: fake", "Exit code: 1"]

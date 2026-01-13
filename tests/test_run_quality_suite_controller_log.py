from __future__ import annotations

import types

import pytest


@pytest.mark.asyncio
async def test_run_quality_suite_merges_controller_log_on_lint_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: fail-fast lint path needs to not drop suite controller_log.

 Prior behavior used dict.setdefault('controller_log', ...), which does not
 overwrite when terminal_command already includes controller_log.
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
    # Back-compat path returns the raw lint payload, but should be enriched.
    assert out.get("status") == "failed"
    assert "suite" in out
    assert "steps" in out

    log = out.get("controller_log")
    assert isinstance(log, list)

    # Existing terminal_command log must be preserved.
    assert log[0] == "Command: fake"

    # Suite log must be present (not dropped).
    assert any(line == "Quality suite run:" for line in log)
    assert any(line == "- Repo: OWNER/REPO" for line in log)
    assert any(line == "- Ref: main" for line in log)

    # Aborted marker must be appended.
    assert log[-1] == "- Aborted: lint failed"

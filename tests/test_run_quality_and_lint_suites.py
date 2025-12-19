import pytest

import github_mcp.tools_workspace as tools_workspace
from github_mcp.workspace_tools import suites


@pytest.mark.asyncio
async def test_run_quality_suite_runs_lint_then_tests(monkeypatch):
    calls = {"lint": 0, "tests": 0}

    async def fake_run_lint_suite(**kwargs):
        calls["lint"] += 1
        return {
            "status": "passed",
            "controller_log": ["lint ran"],
        }

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        return {
            "status": "passed",
            "command": kwargs.get("test_command"),
            "marker": "from_run_tests",
        }

    monkeypatch.setattr(tools_workspace, "run_lint_suite", fake_run_lint_suite)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await suites.run_quality_suite(full_name="owner/repo")

    assert calls == {"lint": 1, "tests": 1}
    assert result["status"] == "passed"
    assert result["marker"] == "from_run_tests"
    assert isinstance(result.get("controller_log"), list)


@pytest.mark.asyncio
async def test_run_lint_suite_forwards_arguments(monkeypatch):
    calls = []

    async def fake_terminal_command(**kwargs):
        calls.append(kwargs)
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {"exit_code": 0},
        }

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await suites.run_lint_suite(
        full_name="owner/repo",
        ref="feature-branch",
        timeout_seconds=456,
        workdir="subdir",
        use_temp_venv=False,
        installing_dependencies=True,
        mutating=True,
    )

    assert result["repo_dir"] == "/tmp/repo"
    assert result["workdir"] == "subdir"
    assert result["result"]["exit_code"] == 0

    assert [c["command"] for c in calls] == [
        "if [ -f scripts/run_lint.sh ]; then bash scripts/run_lint.sh; else python -m ruff check .; fi",
    ]

    lint_call = calls[0]
    assert lint_call == {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "command": "if [ -f scripts/run_lint.sh ]; then bash scripts/run_lint.sh; else python -m ruff check .; fi",
        "timeout_seconds": 456,
        "workdir": "subdir",
        "use_temp_venv": False,
        "installing_dependencies": True,
        "mutating": True,
    }


@pytest.mark.asyncio
async def test_run_lint_suite_respects_custom_lint_command(monkeypatch):
    calls = []

    async def fake_terminal_command(**kwargs):
        calls.append(kwargs)
        return {"result": {"exit_code": 5}}

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await suites.run_lint_suite(full_name="owner/repo", lint_command="mypy .")

    assert result["result"]["exit_code"] == 5
    assert calls[0]["command"] == "mypy ."


@pytest.mark.asyncio
async def test_run_quality_suite_stops_on_lint_failure(monkeypatch):
    calls = {"lint": 0, "tests": 0}

    async def fake_run_lint_suite(**kwargs):
        calls["lint"] += 1
        return {"status": "failed", "result": {"exit_code": 7}, "marker": "from_lint"}

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        raise AssertionError("run_tests should not be called when lint fails")

    monkeypatch.setattr(tools_workspace, "run_lint_suite", fake_run_lint_suite)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await suites.run_quality_suite(full_name="owner/repo")

    assert calls == {"lint": 1, "tests": 0}
    assert result["status"] == "failed"
    assert result["marker"] == "from_lint"

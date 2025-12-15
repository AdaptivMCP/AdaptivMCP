import pytest

from github_mcp import tools_workspace


@pytest.mark.asyncio
async def test_run_quality_suite_runs_scan_then_lint_then_tests(monkeypatch):
    calls = {"scan": 0, "lint": 0, "tests": 0}

    async def fake_terminal_command(**kwargs):
        # used by run_quality_suite for scan and by run_lint_suite for lint
        if kwargs["command"] == tools_workspace.TOKENLIKE_SCAN_COMMAND:
            calls["scan"] += 1
        else:
            calls["lint"] += 1
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {"exit_code": 0},
        }

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        return {
            "status": "passed",
            "command": kwargs.get("test_command"),
            "marker": "from_run_tests",
        }

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(full_name="owner/repo")

    assert calls == {"scan": 1, "lint": 1, "tests": 1}
    assert result["status"] == "passed"
    assert result["marker"] == "from_run_tests"
    assert isinstance(result.get("controller_log"), list)


@pytest.mark.asyncio
async def test_run_quality_suite_can_disable_tokenlike_scan(monkeypatch):
    calls = {"scan": 0, "lint": 0, "tests": 0}

    async def fake_terminal_command(**kwargs):
        calls["scan"] += 1
        raise AssertionError("terminal_command should not be called when scan is disabled")

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        return {"status": "failed"}

    # run_lint_suite will call terminal_command for lint only.
    async def fake_terminal_command_lint(**kwargs):
        calls["lint"] += 1
        return {"repo_dir": "/tmp/repo", "workdir": None, "result": {"exit_code": 0}}

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command_lint)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(
        full_name="owner/repo", run_tokenlike_scan=False
    )

    assert calls == {"scan": 0, "lint": 1, "tests": 1}
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_run_lint_suite_runs_scan_then_lint_and_forwards_arguments(monkeypatch):
    calls = []

    async def fake_terminal_command(**kwargs):
        calls.append(kwargs)
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {"exit_code": 0},
        }

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_lint_suite(
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
        tools_workspace.TOKENLIKE_SCAN_COMMAND,
        "ruff check .",
    ]

    lint_call = calls[1]
    assert lint_call == {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "command": "ruff check .",
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
        if kwargs["command"] == tools_workspace.TOKENLIKE_SCAN_COMMAND:
            return {"result": {"exit_code": 0}}
        return {"result": {"exit_code": 5}}

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_lint_suite(full_name="owner/repo", lint_command="mypy .")

    assert result["result"]["exit_code"] == 5
    assert calls[0]["command"] == tools_workspace.TOKENLIKE_SCAN_COMMAND
    assert calls[1]["command"] == "mypy ."


@pytest.mark.asyncio
async def test_run_quality_suite_fails_on_token_scan_workspace_error(monkeypatch):
    calls = {"scan": 0, "lint": 0, "tests": 0}

    async def fake_terminal_command(**kwargs):
        calls["scan"] += 1
        return {"error": {"error": "WorkspaceError", "message": "clone failed"}}

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        raise AssertionError("run_tests should not be called when scan fails")

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(full_name="owner/repo")

    assert calls == {"scan": 1, "lint": 0, "tests": 0}
    assert result["status"] == "failed"
    assert result["command"] == tools_workspace.TOKENLIKE_SCAN_COMMAND
    log = result.get("controller_log") or []
    assert any("Token-like scan failed due to a workspace/command error." in line for line in log)


@pytest.mark.asyncio
async def test_run_quality_suite_stops_on_lint_failure(monkeypatch):
    calls = {"scan": 0, "lint": 0, "tests": 0}

    async def fake_terminal_command(**kwargs):
        # Successful scan so we reach lint
        assert kwargs["command"] == tools_workspace.TOKENLIKE_SCAN_COMMAND
        calls["scan"] += 1
        return {"repo_dir": "/tmp/repo", "workdir": None, "result": {"exit_code": 0}}

    async def fake_terminal_command_lint(**kwargs):
        calls["lint"] += 1
        return {"repo_dir": "/tmp/repo", "workdir": None, "result": {"exit_code": 7}}

    async def fake_run_tests(**kwargs):
        calls["tests"] += 1
        raise AssertionError("run_tests should not be called when lint fails")

    def fake_run_lint_suite(**kwargs):
        raise AssertionError('run_lint_suite should not be called; run_quality_suite uses it internally')

    # Patch terminal_command and run_tests; quality suite uses run_lint_suite internally.
    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)
    # Swap in a failing lint by patching the function call site: monkeypatch run_lint_suite to use our lint failure.
    async def fake_run_lint_suite(**kwargs):
        # run_tokenlike_scan should already be False here
        assert kwargs.get('run_tokenlike_scan') is False
        return {"status": "failed", "result": {"exit_code": 7}, "marker": "from_lint"}

    monkeypatch.setattr(tools_workspace, "run_lint_suite", fake_run_lint_suite)
    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(full_name="owner/repo")

    assert result["status"] == "failed"
    assert result["marker"] == "from_lint"

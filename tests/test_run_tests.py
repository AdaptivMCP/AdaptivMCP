import pytest

from github_mcp import tools_workspace


@pytest.mark.asyncio
async def test_run_tests_success_maps_exit_code_and_arguments(monkeypatch):
    calls = {}

    async def fake_terminal_command(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
            },
        }

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_tests(
        full_name="owner/repo",
        ref="feature-branch",
        test_command="pytest -q",
        timeout_seconds=123,
        workdir="subdir",
        use_temp_venv=False,
        installing_dependencies=True,
        mutating=True,
    )

    assert result["status"] == "passed"
    assert result["command"] == "pytest -q"
    assert result["exit_code"] == 0
    assert result["repo_dir"] == "/tmp/repo"
    assert result["workdir"] == "subdir"
    assert result["result"]["stdout"] == "ok"

    assert calls["kwargs"] == {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "command": "pytest -q",
        "timeout_seconds": 123,
        "workdir": "subdir",
        "use_temp_venv": False,
        "installing_dependencies": True,
        "mutating": True,
    }


@pytest.mark.asyncio
async def test_run_tests_failed_exit_code_sets_failed_status(monkeypatch):
    async def fake_terminal_command(**kwargs):
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {
                "exit_code": 3,
                "stdout": "failing tests",
                "stderr": "traceback",
            },
        }

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_tests(full_name="owner/repo")

    assert result["status"] == "failed"
    assert result["command"] == "pytest"
    assert result["exit_code"] == 3
    assert result["result"]["stdout"] == "failing tests"
    assert result["result"]["stderr"] == "traceback"


@pytest.mark.asyncio
async def test_run_tests_propagates_structured_error_from_terminal_command(monkeypatch):
    error_payload = {"error": "CloneFailed", "message": "unable to clone repo"}

    async def fake_terminal_command(**kwargs):
        return {"error": error_payload}

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_tests(full_name="owner/repo")

    assert result["status"] == "failed"
    assert result["command"] == "pytest"
    assert result["error"] is error_payload


@pytest.mark.asyncio
async def test_run_tests_handles_unexpected_result_shape(monkeypatch):
    unexpected = {"unexpected": True}

    async def fake_terminal_command(**kwargs):
        return unexpected

    monkeypatch.setattr(tools_workspace, "terminal_command", fake_terminal_command)

    result = await tools_workspace.run_tests(full_name="owner/repo")

    assert result["status"] == "failed"
    assert result["command"] == "pytest"
    error = result["error"]
    assert error["error"] == "UnexpectedResultShape"
    assert "unexpected result structure" in error["message"]
    assert error["raw_result"] is unexpected

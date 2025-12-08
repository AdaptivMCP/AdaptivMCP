import pytest

from github_mcp import tools_workspace


@pytest.mark.asyncio
async def test_run_quality_suite_delegates_to_run_tests_with_all_arguments(monkeypatch):
    calls = {}

    async def fake_run_tests(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "status": "passed",
            "command": kwargs.get("test_command"),
            "marker": "from_run_tests",
        }

    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(
        full_name="owner/repo",
        ref="feature-branch",
        test_command="pytest -q",
        timeout_seconds=321,
        workdir="subdir",
        patch="diff",
        use_temp_venv=False,
        installing_dependencies=True,
        mutating=True,
    )

    assert result["status"] == "passed"
    assert result["command"] == "pytest -q"
    assert result["marker"] == "from_run_tests"

    assert calls["kwargs"] == {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "test_command": "pytest -q",
        "timeout_seconds": 321,
        "workdir": "subdir",
        "patch": "diff",
        "use_temp_venv": False,
        "installing_dependencies": True,
        "mutating": True,
    }


@pytest.mark.asyncio
async def test_run_quality_suite_uses_default_pytest_command(monkeypatch):
    captured = {}

    async def fake_run_tests(**kwargs):
        captured["kwargs"] = kwargs
        return {"status": "failed"}

    monkeypatch.setattr(tools_workspace, "run_tests", fake_run_tests)

    result = await tools_workspace.run_quality_suite(full_name="owner/repo")

    assert result["status"] == "failed"
    forwarded = captured["kwargs"]
    assert forwarded["full_name"] == "owner/repo"
    assert forwarded["ref"] == "main"
    assert forwarded["test_command"] == "pytest"
    assert forwarded["timeout_seconds"] == 600
    assert forwarded["workdir"] is None
    assert forwarded["patch"] is None
    assert forwarded["use_temp_venv"] is True
    assert forwarded["installing_dependencies"] is False
    assert forwarded["mutating"] is False


@pytest.mark.asyncio
async def test_run_lint_suite_uses_default_ruff_command_and_forwards_arguments(monkeypatch):
    calls = {}

    async def fake_run_command(**kwargs):
        calls["kwargs"] = kwargs
        return {
            "repo_dir": "/tmp/repo",
            "workdir": kwargs.get("workdir"),
            "result": {"exit_code": 0},
        }

    monkeypatch.setattr(tools_workspace, "run_command", fake_run_command)

    result = await tools_workspace.run_lint_suite(
        full_name="owner/repo",
        ref="feature-branch",
        timeout_seconds=456,
        workdir="subdir",
        patch="diff",
        use_temp_venv=False,
        installing_dependencies=True,
        mutating=True,
    )

    assert result["repo_dir"] == "/tmp/repo"
    assert result["workdir"] == "subdir"
    assert result["result"]["exit_code"] == 0

    assert calls["kwargs"] == {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "command": "ruff check .",
        "timeout_seconds": 456,
        "workdir": "subdir",
        "patch": "diff",
        "use_temp_venv": False,
        "installing_dependencies": True,
        "mutating": True,
    }


@pytest.mark.asyncio
async def test_run_lint_suite_respects_custom_lint_command(monkeypatch):
    seen = {}

    async def fake_run_command(**kwargs):
        seen["kwargs"] = kwargs
        return {"result": {"exit_code": 5}}

    monkeypatch.setattr(tools_workspace, "run_command", fake_run_command)

    result = await tools_workspace.run_lint_suite(
        full_name="owner/repo",
        lint_command="mypy .",
    )

    assert result["result"]["exit_code"] == 5
    forwarded = seen["kwargs"]
    assert forwarded["command"] == "mypy ."
    assert forwarded["full_name"] == "owner/repo"
    assert forwarded["ref"] == "main"

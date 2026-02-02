from __future__ import annotations

import pytest

import github_mcp.workspace_tools.suites as suites


def _runner_stdout(step_results: dict[str, tuple[int, str]]) -> str:
    out: list[str] = []
    for name, (rc, body) in step_results.items():
        out.append(f"__MCP_STEP_BEGIN__{name}\n")
        if body:
            out.append(body if body.endswith("\n") else (body + "\n"))
        out.append(f"\n__MCP_STEP_END__{name}::{rc}::12\n")
    return "".join(out)


def test_parse_marked_steps_malformed_numbers_become_none() -> None:
    out = (
        "__MCP_STEP_BEGIN__alpha\nhello\n__MCP_STEP_END__alpha::not-an-int::also-bad\n"
    )
    steps = suites._parse_marked_steps(out)
    assert steps[0]["name"] == "alpha"
    assert steps[0]["exit_code"] is None
    assert steps[0]["duration_ms"] is None


def test_looks_like_mocked_terminal_command_covers_false_paths() -> None:
    assert suites._looks_like_mocked_terminal_command("nope") is False
    assert suites._looks_like_mocked_terminal_command({"exit_code": 1}) is False
    assert (
        suites._looks_like_mocked_terminal_command({"exit_code": 0, "stdout": "x"})
        is False
    )
    assert (
        suites._looks_like_mocked_terminal_command(
            {"exit_code": 0, "stdout": "", "stderr": ""}
        )
        is True
    )


@pytest.mark.anyio
async def test_run_named_step_can_include_raw_and_skip_missing_command(monkeypatch):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 127, "stdout": "missing\n", "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    step = await suites._run_named_step(
        name="optional_tool",
        full_name="owner/repo",
        ref="main",
        command="does-not-exist",
        timeout_seconds=1,
        workdir=None,
        use_temp_venv=False,
        installing_dependencies=False,
        include_raw=True,
        allow_missing_command=True,
    )

    assert step["status"] == "skipped"
    assert "raw" in step


@pytest.mark.anyio
async def test_run_tests_adds_cov_fail_under_parallel_and_timeout_flags(monkeypatch):
    seen: dict[str, str] = {}

    async def fake_run_named_step(**kwargs):
        seen["command"] = kwargs["command"]
        return {"name": "tests", "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_tests(
        full_name="owner/repo",
        ref="main",
        test_command="pytest -q",
        cov_fail_under=50,
        parallel=True,
        parallel_workers="2",
        timeout_per_test_seconds=10,
    )

    assert res["status"] == "passed"
    cmd = seen["command"]
    assert "--cov=." in cmd
    assert "--cov-fail-under=50" in cmd
    assert " -n 2" in cmd
    assert "--timeout=10" in cmd


@pytest.mark.anyio
async def test_run_tests_does_not_duplicate_existing_flags(monkeypatch):
    seen: dict[str, str] = {}

    base = "pytest -q --cov=foo --cov-report=xml --cov-fail-under=1 -n 2 --timeout=5"

    async def fake_run_named_step(**kwargs):
        seen["command"] = kwargs["command"]
        return {"name": "tests", "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    await suites.run_tests(
        full_name="owner/repo",
        ref="main",
        test_command=base,
        coverage=True,
        cov_fail_under=10,
        parallel=True,
        timeout_per_test_seconds=20,
    )

    assert seen["command"] == base


@pytest.mark.anyio
async def test_run_lint_suite_multi_command_aborts_on_format_fail(monkeypatch):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        if name == "format":
            return {"name": name, "status": "failed", "summary": {"exit_code": 1}}
        return {"name": name, "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_lint_suite(
        full_name="owner/repo",
        ref="main",
        use_temp_venv=False,
        installing_dependencies=False,
        include_format_check=True,
        format_command="fmt",
        lint_command="lint",
        fail_fast=True,
    )

    assert calls == ["format"]
    assert res["status"] == "failed"
    assert any("Aborted: format failed" in line for line in res["controller_log"])


@pytest.mark.anyio
@pytest.mark.parametrize("include_raw", [False, True])
async def test_run_lint_suite_single_runner_missing_markers_is_failure(
    monkeypatch, include_raw: bool
):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": "hello\n", "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_lint_suite(
        full_name="owner/repo",
        ref="main",
        use_temp_venv=True,
        installing_dependencies=True,
        include_format_check=True,
        format_command="fmt",
        lint_command="lint",
        include_raw_step_outputs=include_raw,
    )

    assert res["status"] == "failed"
    assert res["steps"][0]["name"] == "runner"
    if include_raw:
        assert "raw" in res["steps"][0]


@pytest.mark.anyio
async def test_run_lint_suite_single_runner_parses_markers(monkeypatch):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            stdout = _runner_stdout({"format": (0, "ok"), "lint": (0, "ok")})
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": stdout, "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_lint_suite(
        full_name="owner/repo",
        ref="main",
        use_temp_venv=True,
        installing_dependencies=True,
        include_format_check=True,
        format_command="fmt",
        lint_command="lint",
    )

    assert res["status"] == "passed"
    assert [s["name"] for s in res["steps"]] == ["format", "lint"]


@pytest.mark.anyio
async def test_run_quality_suite_developer_defaults_and_auto_fix_modify_commands(
    monkeypatch,
):
    seen: dict[str, list[str]] = {"names": [], "commands": []}

    async def fake_run_named_step(*, name: str, command: str, **kwargs):
        seen["names"].append(name)
        seen["commands"].append(command)
        return {"name": name, "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=True,
        auto_fix=True,
        lint_command="ruff check .",
        test_command="pytest -q",
        # leave format/typecheck/security unset to exercise developer defaults
        format_command=None,
        typecheck_command=None,
        security_command=None,
    )

    assert res["status"] == "passed"
    # Optional steps run before required steps.
    assert seen["names"][:3] == ["format", "typecheck", "security"]
    # Auto-fix: formatter drops --check, linter gains --fix.
    assert seen["commands"][0].startswith("ruff format ")
    assert "--check" not in seen["commands"][0]
    assert seen["commands"][3].startswith("ruff check --fix")  # lint step


@pytest.mark.anyio
async def test_run_quality_suite_preflight_adds_preflight_steps(monkeypatch):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        return {"name": name, "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=True,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
    )

    assert res["status"] == "passed"
    assert calls[:4] == [
        "python_version",
        "pip_version",
        "ruff_version",
        "pytest_version",
    ]
    assert calls[-2:] == ["lint", "tests"]
    assert any("Preflight: enabled" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_aborts_on_lint_failure(monkeypatch):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            stdout = _runner_stdout({"lint": (1, "bad")})
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": stdout, "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=True,
        installing_dependencies=True,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
    )

    assert res["status"] == "failed"
    assert [s["name"] for s in res["steps"]] == ["lint"]
    assert any("Aborted: lint failed" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_no_tests_status_and_raw(monkeypatch):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            stdout = _runner_stdout({"lint": (0, "ok"), "tests": (5, "none")})
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": stdout, "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=True,
        installing_dependencies=True,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
        include_raw_step_outputs=True,
    )

    assert res["status"] == "no_tests"
    assert [s["name"] for s in res["steps"]] == ["lint", "tests"]
    assert all("raw" in s for s in res["steps"])


@pytest.mark.anyio
async def test_run_lint_suite_single_runner_failing_step_sets_failed_and_includes_raw(
    monkeypatch,
):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            stdout = _runner_stdout({"format": (0, "ok"), "lint": (1, "bad")})
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": stdout, "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_lint_suite(
        full_name="owner/repo",
        ref="main",
        use_temp_venv=True,
        installing_dependencies=True,
        include_format_check=True,
        format_command="fmt",
        lint_command="lint",
        include_raw_step_outputs=True,
    )

    assert res["status"] == "failed"
    assert [s["name"] for s in res["steps"]] == ["format", "lint"]
    assert all("raw" in s for s in res["steps"])


@pytest.mark.anyio
async def test_run_quality_suite_multi_command_lint_failure_aborts(monkeypatch):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        if name == "lint":
            return {"name": name, "status": "failed", "summary": {"exit_code": 1}}
        return {"name": name, "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
    )

    assert calls == ["lint"]
    assert res["status"] == "failed"
    assert any("Aborted: lint failed" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_multi_command_no_tests_status(monkeypatch):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        if name == "tests":
            return {"name": name, "status": "passed", "summary": {"exit_code": 5}}
        return {"name": name, "status": "passed", "summary": {"exit_code": 0}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
    )

    assert calls == ["lint", "tests"]
    assert res["status"] == "no_tests"


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_missing_markers_failure_without_raw(
    monkeypatch,
):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": "hello\n", "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=True,
        installing_dependencies=True,
        developer_defaults=False,
        lint_command="lint",
        test_command="tests",
        include_raw_step_outputs=False,
    )

    assert res["status"] == "failed"
    assert res["steps"][0]["name"] == "runner"
    assert "raw" not in res["steps"][0]


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_gate_optional_steps_aborts_on_optional_failure(
    monkeypatch,
):
    class DummyTW:
        async def terminal_command(self, **kwargs):
            stdout = _runner_stdout({"format": (1, "bad")})
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": stdout, "stderr": ""},
            }

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=True,
        installing_dependencies=True,
        developer_defaults=False,
        format_command="fmt",
        lint_command="lint",
        test_command="tests",
        gate_optional_steps=True,
        fail_fast=True,
    )

    assert res["status"] == "failed"
    assert [s["name"] for s in res["steps"]] == ["format"]
    assert any("Aborted: format failed" in line for line in res["controller_log"])

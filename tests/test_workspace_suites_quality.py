from __future__ import annotations

import pytest

import github_mcp.workspace_tools.suites as suites


def _step(name: str, *, status: str, exit_code: int) -> dict:
    return {
        "name": name,
        "status": status,
        "summary": {"exit_code": exit_code, "duration_ms": 1},
    }


def _runner_stdout(step_results: dict[str, tuple[int, str]]) -> str:
    """Build stdout with __MCP_STEP_BEGIN__/__MCP_STEP_END__ markers."""

    out: list[str] = []
    for name, (rc, body) in step_results.items():
        out.append(f"__MCP_STEP_BEGIN__{name}\n")
        if body:
            out.append(body if body.endswith("\n") else (body + "\n"))
        # runner emits a leading newline before END
        out.append(f"\n__MCP_STEP_END__{name}::{rc}::12\n")
    return "".join(out)


@pytest.mark.anyio
async def test_run_quality_suite_multi_command_optional_failures_become_warnings(
    monkeypatch,
):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        if name == "format":
            return _step(name, status="failed", exit_code=1)
        return _step(name, status="passed", exit_code=0)

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=False,
        format_command="fmt",
        typecheck_command="type",
        security_command="sec",
        lint_command="lint",
        test_command="tests",
        gate_optional_steps=False,
        fail_fast=True,
    )

    assert calls == ["format", "typecheck", "security", "lint", "tests"]
    assert res["status"] == "passed_with_warnings"
    assert any("optional steps failed" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_multi_command_gate_optional_steps_aborts(monkeypatch):
    calls: list[str] = []

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        if name == "format":
            return _step(name, status="failed", exit_code=1)
        return _step(name, status="passed", exit_code=0)

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    res = await suites.run_quality_suite(
        full_name="owner/repo",
        ref="main",
        preflight=False,
        use_temp_venv=False,
        installing_dependencies=False,
        developer_defaults=False,
        format_command="fmt",
        lint_command="lint",
        test_command="tests",
        gate_optional_steps=True,
        fail_fast=True,
    )

    assert calls == ["format"]
    assert res["status"] == "failed"
    assert any("Aborted: format failed" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_parses_markers_and_warns(monkeypatch):
    # Force the single-runner path.
    step_results = {
        "format": (1, "fmt failed"),
        "lint": (0, "lint ok"),
        "tests": (0, "tests ok"),
    }

    class DummyTW:
        async def terminal_command(self, **kwargs):
            return {
                "command_input": kwargs.get("command"),
                "result": {
                    "exit_code": 0,
                    "stdout": _runner_stdout(step_results),
                    "stderr": "",
                },
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
        gate_optional_steps=False,
        fail_fast=True,
    )

    assert res["status"] == "passed_with_warnings"
    step_names = [s.get("name") for s in res["steps"]]
    assert step_names == ["format", "lint", "tests"]
    fmt = res["steps"][0]
    assert fmt["status"] == "failed"
    assert "fmt failed" in fmt["summary"]["stdout"]


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_mocked_terminal_falls_back(monkeypatch):
    calls: list[str] = []

    class DummyTW:
        async def terminal_command(self, **kwargs):
            # Looks like a unit-test stub: rc=0, empty stdout/stderr.
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": "", "stderr": ""},
            }

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        return _step(name, status="passed", exit_code=0)

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())
    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

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

    assert res["status"] == "passed"
    assert calls == ["lint", "tests"]
    assert any("mocked terminal_command" in line for line in res["controller_log"])


@pytest.mark.anyio
async def test_run_quality_suite_single_runner_missing_markers_is_hard_failure(
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
        include_raw_step_outputs=True,
    )

    assert res["status"] == "failed"
    assert res["steps"][0]["name"] == "runner"
    assert res["steps"][0]["raw"]["result"]["stdout"] == "hello\n"

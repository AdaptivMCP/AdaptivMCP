import asyncio


def test_suites_module_imports():
    import github_mcp.workspace_tools.suites as _suites  # noqa: F401


def test_step_status_from_exit_code_cases():
    from github_mcp.workspace_tools import suites

    assert suites._step_status_from_exit_code(exit_code=0, allow_missing_command=False) == "passed"
    assert suites._step_status_from_exit_code(exit_code=3, allow_missing_command=False) == "failed"
    assert suites._step_status_from_exit_code(exit_code=None, allow_missing_command=False) == "failed"
    assert suites._step_status_from_exit_code(exit_code=127, allow_missing_command=True) == "skipped"
    assert suites._step_status_from_exit_code(exit_code=127, allow_missing_command=False) == "failed"


def test_parse_marked_steps_captures_output_and_durations():
    from github_mcp.workspace_tools import suites

    out = (
        "__MCP_STEP_BEGIN__alpha\n"
        "line 1\n"
        "line 2\n"
        "__MCP_STEP_BEGIN__beta\n"  # alpha never ended
        "beta out\n"
        "__MCP_STEP_END__beta::0::12\n"
        "__MCP_STEP_BEGIN__gamma\n"
        "gamma out\n"
    )

    steps = suites._parse_marked_steps(out)

    assert steps[0]["name"] == "alpha"
    assert steps[0]["exit_code"] is None
    assert "line 1" in steps[0]["output"]

    assert steps[1]["name"] == "beta"
    assert steps[1]["exit_code"] == 0
    assert steps[1]["duration_ms"] == 12
    assert steps[1]["output"].strip() == "beta out"

    assert steps[2]["name"] == "gamma"
    assert steps[2]["exit_code"] is None
    assert "gamma out" in steps[2]["output"]


def test_stream_normalization_and_text_stats():
    from github_mcp.workspace_tools import suites

    raw = "a\r\nb\rc"
    normalized = suites._normalize_stream_text(raw)
    assert normalized == "a\nb\nc"

    chars, lines = suites._text_stats(raw)
    assert chars == len("a\nb\nc")
    assert lines == 3


def test_slim_terminal_command_payload_normalizes_and_counts():
    from github_mcp.workspace_tools import suites

    payload = {
        "command_input": "echo hi",
        "result": {"exit_code": 0, "stdout": "a\rb\n", "stderr": "x\r\n"},
    }

    slim = suites._slim_terminal_command_payload(payload)
    assert slim["command"] == "echo hi"
    assert slim["exit_code"] == 0
    assert slim["stdout"] == "a\nb\n"
    assert slim["stderr"] == "x\n"
    assert slim["stdout_stats"]["lines"] == 3  # a, b, blank

    assert suites._slim_terminal_command_payload("nope")["raw"] == "nope"


def test_run_tests_adds_cov_flags_and_no_tests_status(monkeypatch):
    import github_mcp.workspace_tools.suites as suites

    seen = {}

    async def fake_run_named_step(**kwargs):
        seen.update(kwargs)
        # exit_code=5 means "no tests collected"
        return {"name": "tests", "status": "passed", "summary": {"exit_code": 5, "duration_ms": 1}}

    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    result = asyncio.run(
        suites.run_tests(
            full_name="owner/repo",
            ref="main",
            test_command="pytest -q",
            coverage=True,
            cov_target="github_mcp",
        )
    )

    assert result["status"] == "no_tests"
    assert "--cov=github_mcp" in seen["command"]
    assert "--cov-report=" in seen["command"]


def test_run_lint_suite_falls_back_when_terminal_command_is_mocked(monkeypatch):
    import github_mcp.workspace_tools.suites as suites

    calls: list[str] = []

    class DummyTW:
        async def terminal_command(self, **kwargs):
            # Simulate a unit-test stub that does not execute the command.
            return {
                "command_input": kwargs.get("command"),
                "result": {"exit_code": 0, "stdout": "", "stderr": ""},
            }

    async def fake_run_named_step(*, name: str, **kwargs):
        calls.append(name)
        return {"name": name, "status": "passed", "summary": {"exit_code": 0, "duration_ms": 1}}

    monkeypatch.setattr(suites, "_tw", lambda: DummyTW())
    monkeypatch.setattr(suites, "_run_named_step", fake_run_named_step)

    out = asyncio.run(
        suites.run_lint_suite(
            full_name="owner/repo",
            ref="main",
            use_temp_venv=True,
            installing_dependencies=True,
            include_format_check=True,
            format_command="ruff format --check .",
            lint_command="ruff check .",
        )
    )

    assert out["status"] == "passed"
    assert calls == ["format", "lint"]
    assert any("mocked terminal_command" in line for line in out["controller_log"])

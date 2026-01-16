"""Run developer-quality suites in the persistent repo mirror.

This module provides three public tools:
- run_lint_suite
- run_tests
- run_quality_suite

Design goals:
- Single canonical repo selector: full_name ("owner/repo") + ref.
- No legacy alias inputs.
- No output truncation.
- Stable, minimal, structured outputs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from github_mcp.server import mcp_tool
from github_mcp.utils import _normalize_timeout_seconds


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _text_stats(text: str) -> Tuple[int, int]:
    if not text:
        return (0, 0)
    return (len(text), text.count("\n") + 1)


def _slim_terminal_command_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"raw": str(payload)}

    res = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    stdout = (res.get("stdout") or "") if isinstance(res, dict) else ""
    stderr = (res.get("stderr") or "") if isinstance(res, dict) else ""
    out_chars, out_lines = _text_stats(stdout)
    err_chars, err_lines = _text_stats(stderr)

    return {
        "command": payload.get("command_input") or payload.get("command"),
        "exit_code": res.get("exit_code") if isinstance(res, dict) else None,
        "timed_out": bool(res.get("timed_out")) if isinstance(res, dict) else False,
        "stdout_stats": {"chars": out_chars, "lines": out_lines},
        "stderr_stats": {"chars": err_chars, "lines": err_lines},
        "stdout": stdout,
        "stderr": stderr,
    }


async def _run_named_step(
    *,
    name: str,
    full_name: str,
    ref: str,
    command: str,
    timeout_seconds: int,
    workdir: Optional[str],
    use_temp_venv: bool,
    installing_dependencies: bool,
    include_raw: bool,
    allow_missing_command: bool = False,
) -> Dict[str, Any]:
    raw = await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )

    slim = _slim_terminal_command_payload(raw)
    exit_code = slim.get("exit_code")

    # Some optional checks may not be installed in the execution environment.
    # Treat "command not found" as a skip when allowed.
    if allow_missing_command and exit_code == 127:
        status = "skipped"
    else:
        status = "passed" if exit_code == 0 else "failed"

    step: Dict[str, Any] = {
        "name": name,
        "status": status,
        "summary": slim,
    }
    if include_raw:
        step["raw"] = raw
    return step


@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = False,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
    timeout_seconds_i = _normalize_timeout_seconds(timeout_seconds, 600)

    result = await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds_i,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )

    if isinstance(result, dict) and "error" in result:
        return {
            "status": "failed",
            "command": test_command,
            "error": result["error"],
            "controller_log": [
                "Test run failed due to a repo mirror or command error.",
                f"- Command: {test_command}",
                f"- Error: {result['error'].get('error')}",
            ],
        }

    if not isinstance(result, dict) or "result" not in result:
        return {
            "status": "failed",
            "command": test_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "terminal_command returned an unexpected result structure",
                "raw_result": result,
            },
            "controller_log": [
                "Test run failed because terminal_command returned an unexpected result shape.",
                f"- Command: {test_command}",
            ],
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")

    status = "passed" if exit_code == 0 else ("no_tests" if exit_code == 5 else "failed")

    return {
        "status": status,
        "command": test_command,
        "exit_code": exit_code,
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": [
            "Completed test command in repo mirror:",
            f"- Repo: {full_name}",
            f"- Ref: {ref}",
            f"- Command: {test_command}",
            f"- Status: {status}",
            f"- Exit code: {exit_code}",
        ],
    }


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "ruff check .",
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = False,
    installing_dependencies: bool = False,
) -> Dict[str, Any]:
    timeout_seconds_i = _normalize_timeout_seconds(timeout_seconds, 600)

    return await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds_i,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
    )


@mcp_tool(write_action=False)
async def run_quality_suite(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest -q",
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = True,
    lint_command: str = "ruff check .",
    format_command: Optional[str] = None,
    typecheck_command: Optional[str] = None,
    security_command: Optional[str] = None,
    preflight: bool = True,
    fail_fast: bool = True,
    include_raw_step_outputs: bool = False,
    *,
    developer_defaults: bool = True,
    auto_fix: bool = False,
    gate_optional_steps: bool = False,
) -> Dict[str, Any]:
    timeout_seconds_i = _normalize_timeout_seconds(timeout_seconds, 600)

    # Developer defaults are enabled by default for this self-hosted MCP server.
    # The intent is to provide a useful suite out-of-the-box, even when invoked
    # via automation.
    if developer_defaults:
        if format_command is None:
            # Ruff is already the canonical formatter in this repo.
            format_command = "ruff format --check ."
        if typecheck_command is None:
            # Prefer a universally-available type/compile sanity check.
            # Projects can override this with mypy/pyright/pyre if desired.
            typecheck_command = "python -m compileall -q ."
        if security_command is None:
            # pip check is cheap and catches incompatible dependency constraints.
            security_command = "python -m pip check"

    # If auto-fix is enabled, prefer fix-capable commands.
    if auto_fix:
        if format_command and "--check" in format_command:
            format_command = format_command.replace("--check ", "")
        if lint_command.startswith("ruff check") and "--fix" not in lint_command:
            lint_command = lint_command.replace("ruff check", "ruff check --fix")

    suite: Dict[str, Any] = {
        "repo": full_name,
        "ref": ref,
        "workdir": workdir,
        "timeout_seconds": timeout_seconds_i,
        "commands": {
            "format": format_command,
            "lint": lint_command,
            "typecheck": typecheck_command,
            "security": security_command,
            "tests": test_command,
        },
        "options": {
            "preflight": bool(preflight),
            "fail_fast": bool(fail_fast),
            "gate_optional_steps": bool(gate_optional_steps),
            "use_temp_venv": bool(use_temp_venv),
            "installing_dependencies": bool(installing_dependencies),
            "developer_defaults": bool(developer_defaults),
        },
    }

    controller_log: List[str] = [
        "Quality suite run:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
    ]

    steps: List[Dict[str, Any]] = []

    optional_failures: List[str] = []

    async def run_optional(name: str, command: Optional[str]) -> Optional[Dict[str, Any]]:
        if not command:
            return None
        step = await _run_named_step(
            name=name,
            full_name=full_name,
            ref=ref,
            command=command,
            timeout_seconds=timeout_seconds_i,
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            include_raw=include_raw_step_outputs,
            allow_missing_command=True,
        )
        steps.append(step)

        # Optional steps are informative by default. When they fail, surface a
        # warning signal without failing the overall suite unless explicitly
        # requested via gate_optional_steps.
        if step.get("status") == "failed" and not gate_optional_steps:
            optional_failures.append(name)

        # Optional steps are informative by default; do not gate the suite unless explicitly requested.
        if gate_optional_steps and fail_fast and step.get("status") == "failed":
            controller_log.append(f"- Aborted: {name} failed")
            return step
        return step

    if preflight:
        controller_log.append("- Preflight: enabled")
        # Diagnostics only; no gating.
        steps.append(
            await _run_named_step(
                name="python_version",
                full_name=full_name,
                ref=ref,
                command="python --version",
                timeout_seconds=min(60, timeout_seconds_i),
                workdir=workdir,
                use_temp_venv=use_temp_venv,
                installing_dependencies=False,
                include_raw=include_raw_step_outputs,
            )
        )
        steps.append(
            await _run_named_step(
                name="pip_version",
                full_name=full_name,
                ref=ref,
                command="python -m pip --version",
                timeout_seconds=min(60, timeout_seconds_i),
                workdir=workdir,
                use_temp_venv=use_temp_venv,
                installing_dependencies=False,
                include_raw=include_raw_step_outputs,
            )
        )

    # Optional developer checks.
    for name, cmd in (
        ("format", format_command),
        ("typecheck", typecheck_command),
        ("security", security_command),
    ):
        step = await run_optional(name, cmd)
        if (
            gate_optional_steps
            and step is not None
            and fail_fast
            and step.get("status") == "failed"
        ):
            return {
                "status": "failed",
                "suite": suite,
                "steps": steps,
                "controller_log": controller_log,
            }

    # Lint is required.
    lint_step = await _run_named_step(
        name="lint",
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds_i,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        include_raw=include_raw_step_outputs,
    )
    steps.append(lint_step)
    if lint_step.get("status") == "failed":
        controller_log.append("- Aborted: lint failed")
        return {
            "status": "failed",
            "suite": suite,
            "steps": steps,
            "controller_log": controller_log,
        }

    # Tests are required.
    tests_step = await _run_named_step(
        name="tests",
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds_i,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        include_raw=include_raw_step_outputs,
    )
    steps.append(tests_step)

    tests_exit = (tests_step.get("summary") or {}).get("exit_code")
    if tests_exit == 5:
        status = "no_tests"
    else:
        status = "passed" if tests_step.get("status") == "passed" else "failed"

    if status in {"passed", "no_tests"} and optional_failures:
        controller_log.append(
            "- Warnings: optional steps failed: " + ", ".join(sorted(set(optional_failures)))
        )
        if status == "passed":
            status = "passed_with_warnings"

    controller_log.append(f"- Status: {status}")

    return {
        "status": status,
        "suite": suite,
        "steps": steps,
        "controller_log": controller_log,
    }

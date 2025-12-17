# Split from github_mcp.tools_workspace (generated).
from typing import Any, Dict, List, Optional

from github_mcp.server import (
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


TOKENLIKE_SCAN_COMMAND = (
    "if [ -f scripts/check_no_tokenlike_strings.py ]; then "
    "python scripts/check_no_tokenlike_strings.py; "
    "else echo 'token scan skipped: scripts/check_no_tokenlike_strings.py not found'; fi"
)


@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "if [ -f scripts/run_tests.sh ]; then bash scripts/run_tests.sh; else python -m pytest; fi",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the project's test command in the persistent workspace and summarize the result."""
    result = await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    if isinstance(result, dict) and "error" in result:
        # Structured error from run_command (e.g. auth/clone failure).
        return {
            "status": "failed",
            "command": test_command,
            "error": result["error"],
            "controller_log": [
                "Test run failed due to a workspace or command error.",
                f"- Command: {test_command}",
                f"- Error: {result['error'].get('error')}",
            ],
        }

    if not isinstance(result, dict) or "result" not in result:
        # Unexpected shape from run_command.
        return {
            "status": "failed",
            "command": test_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "terminal_command returned an unexpected result structure",
                "raw_result": result,
            },
            "controller_log": [
                "Test run failed because run_command returned an unexpected result shape.",
                f"- Command: {test_command}",
            ],
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"

    summary_lines = [
        "Completed test command in workspace:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Command: {test_command}",
        f"- Status: {status}",
        f"- Exit code: {exit_code}",
    ]

    return {
        "status": status,
        "command": test_command,
        "exit_code": exit_code,
        "repo_dir": result.get("repo_dir"),
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": summary_lines,
    }


@mcp_tool(write_action=False)
async def run_quality_suite(
    full_name: str,
    ref: str = "main",
    test_command: str = "if [ -f scripts/run_tests.sh ]; then bash scripts/run_tests.sh; else python -m pytest; fi",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    lint_command: str = "if [ -f scripts/run_lint.sh ]; then bash scripts/run_lint.sh; else python -m ruff check .; fi",
    run_tokenlike_scan: bool = True,
) -> Dict[str, Any]:
    """Run the standard quality/test suite for a repo/ref.

    This executes, in order:
      1) Optional token-like string scan (only if the repo contains the scanner script)
      2) Lint/static analysis via `run_lint_suite`
      3) Tests via `run_tests`

    The scan step helps prevent upstream OpenAI blocks and accidental leakage by
    ensuring token-shaped strings are not committed into docs/tests/examples.
    """

    controller_log: List[str] = [
        "Quality suite run:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Token-like scan: {'enabled' if run_tokenlike_scan else 'disabled'}",
        f"- Lint command: {lint_command}",
        f"- Test command: {test_command}",
    ]

    if run_tokenlike_scan:
        scan_result = await _tw().terminal_command(
            full_name=full_name,
            ref=ref,
            command=TOKENLIKE_SCAN_COMMAND,
            timeout_seconds=min(timeout_seconds, 300),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            mutating=mutating,
        )
        if isinstance(scan_result, dict) and "error" in scan_result:
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "error": scan_result["error"],
                "controller_log": controller_log
                + ["Token-like scan failed due to a workspace/command error."],
            }
        cmd = (scan_result or {}).get("result") or {}
        exit_code = cmd.get("exit_code")
        if exit_code not in (0, None):
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "exit_code": exit_code,
                "repo_dir": scan_result.get("repo_dir"),
                "workdir": scan_result.get("workdir"),
                "result": cmd,
                "controller_log": controller_log
                + ["Token-like scan failed; replace secrets with <REDACTED> placeholders."],
            }
        controller_log.append("- Token-like scan: passed (or skipped)")

    lint_result = await _tw().run_lint_suite(
        full_name=full_name,
        ref=ref,
        lint_command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
        run_tokenlike_scan=False,
    )
    if (lint_result or {}).get("status") != "passed":
        lint_result.setdefault("controller_log", controller_log + ["- Lint: failed"])
        return lint_result
    controller_log.append("- Lint: passed")

    tests_result = await _tw().run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )
    status = tests_result.get("status") or "unknown"
    controller_log.append(f"- Tests: {status}")

    existing_log = tests_result.get("controller_log")
    if isinstance(existing_log, list):
        controller_log.extend(existing_log)

    tests_result["controller_log"] = controller_log
    return tests_result


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "if [ -f scripts/run_lint.sh ]; then bash scripts/run_lint.sh; else python -m ruff check .; fi",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    run_tokenlike_scan: bool = True,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the lint or static-analysis command in the workspace."""

    if run_tokenlike_scan:
        scan_result = await _tw().terminal_command(
            full_name=full_name,
            ref=ref,
            command=TOKENLIKE_SCAN_COMMAND,
            timeout_seconds=min(timeout_seconds, 300),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            mutating=mutating,
        )
        if isinstance(scan_result, dict) and "error" in scan_result:
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "error": scan_result["error"],
                "controller_log": [
                    "Token-like scan failed due to a workspace or command error.",
                    f"- Repo: {full_name}",
                    f"- Ref: {ref}",
                ],
            }
        cmd = (scan_result or {}).get("result") or {}
        exit_code = cmd.get("exit_code")
        if exit_code not in (0, None):
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "exit_code": exit_code,
                "repo_dir": scan_result.get("repo_dir"),
                "workdir": scan_result.get("workdir"),
                "result": cmd,
                "controller_log": [
                    "Token-like scan failed; replace secrets with <REDACTED> placeholders.",
                    f"- Repo: {full_name}",
                    f"- Ref: {ref}",
                ],
            }

    result = await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    if isinstance(result, dict) and "error" in result:
        return {
            "status": "failed",
            "command": lint_command,
            "error": result["error"],
            "controller_log": [
                "Lint run failed due to a workspace or command error.",
                f"- Command: {lint_command}",
                f"- Error: {result['error'].get('error')}",
            ],
        }

    if not isinstance(result, dict) or "result" not in result:
        return {
            "status": "failed",
            "command": lint_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "terminal_command returned an unexpected result structure",
                "raw_result": result,
            },
            "controller_log": [
                "Lint run failed because run_command returned an unexpected result shape.",
                f"- Command: {lint_command}",
            ],
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"

    summary_lines = [
        "Completed lint command in workspace:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Command: {lint_command}",
        f"- Status: {status}",
        f"- Exit code: {exit_code}",
    ]

    return {
        "status": status,
        "command": lint_command,
        "exit_code": exit_code,
        "repo_dir": result.get("repo_dir"),
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": summary_lines,
    }

# Split from github_mcp.tools_workspace (generated).

from typing import Any, Dict, List, Optional

from github_mcp.server import mcp_tool


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
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
        owner=owner,
        repo=repo,
        branch=branch,
    )

    if isinstance(result, dict) and "error" in result:
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
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": summary_lines,
    }


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "ruff check .",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the lint or static-analysis command in the workspace."""

    return await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        owner=owner,
        repo=repo,
        branch=branch,
    )


@mcp_tool(write_action=False)
async def run_quality_suite(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    lint_command: str = "ruff check .",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run lint and tests for a repo/ref.

    Steps:
      1) Lint/static analysis via `run_lint_suite`
      2) Tests via `run_tests`

    This suite intentionally does not run token-like string scanning. Token
    redaction/sanitization happens at log/serialization boundaries.
    """

    controller_log: List[str] = [
        "Quality suite run:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Lint command: {lint_command}",
        f"- Test command: {test_command}",
    ]

    lint_result = await run_lint_suite(
        full_name=full_name,
        ref=ref,
        lint_command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        owner=owner,
        repo=repo,
        branch=branch,
    )

    if isinstance(lint_result, dict) and lint_result.get("result", {}).get("exit_code") not in (0, None):
        lint_result.setdefault("controller_log", controller_log + ["- Lint: failed"])
        return lint_result
    controller_log.append("- Lint: passed")

    tests_result = await run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        owner=owner,
        repo=repo,
        branch=branch,
    )

    status = tests_result.get("status") or "unknown"
    controller_log.append(f"- Tests: {status}")

    existing_log = tests_result.get("controller_log")
    if isinstance(existing_log, list):
        controller_log.extend(existing_log)

    tests_result["controller_log"] = controller_log
    return tests_result

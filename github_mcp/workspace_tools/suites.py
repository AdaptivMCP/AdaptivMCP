"""Wrappers for running test/lint suites in the persistent workspace.

This file is part of the public "workspace" tool surface.

Developer experience goals:
- Keep the original contract of `run_quality_suite` intact by default.
- Provide richer structured output (steps, diagnostics, suggestions) when requested.
- Provide safe, bounded previews of stdout/stderr that help an AI assistant guide a developer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from github_mcp.server import mcp_tool


def _normalize_timeout_seconds(value: object, default: int) -> int:
    if value is None or isinstance(value, bool):
        return max(1, int(default))
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, float):
        return max(1, int(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return max(1, int(default))
        try:
            return max(1, int(float(s)))
        except Exception:
            return max(1, int(default))
    return max(1, int(default))


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _tail_lines(text: str, max_chars: int = 4000) -> str:
    """Return a tail preview without line limits."""
    if not text:
        return ""
    out = text
    if len(out) > max_chars:
        out = out[-max_chars:]
    return out


def _text_stats(text: str) -> Tuple[int, int]:
    if not text:
        return (0, 0)
    return (len(text), text.count("\n") + 1)


def _extract_missing_module(stdout: str, stderr: str) -> str:
    combined = f"{stderr}\n{stdout}" if (stdout or stderr) else ""
    marker = "ModuleNotFoundError: No module named "
    pos = combined.find(marker)
    if pos == -1:
        return ""
    tail = combined[pos + len(marker) :].strip()
    if not tail:
        return ""
    if tail[:1] in ('"', "'"):
        q = tail[0]
        rest = tail[1:]
        endq = rest.find(q)
        return (rest[:endq] if endq != -1 else rest).strip()
    return (tail.split()[0] if tail else "").strip()


def _extract_command_not_found(stdout: str, stderr: str) -> str:
    combined = f"{stderr}\n{stdout}".lower()
    for marker in (
        "command not found",
        "no such file or directory",
        "is not recognized as an internal or external command",
    ):
        if marker in combined:
            return marker
    return ""


def _slim_terminal_command_payload(payload: Any) -> Dict[str, Any]:
    """Return a stable, bounded view of `terminal_command` output.

    This is used for step summaries; the full `terminal_command` payload may still
    be returned separately for callers that need complete logs.
    """

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
        "stdout_tail": _tail_lines(stdout),
        "stderr_tail": _tail_lines(stderr),
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
    owner: Optional[str],
    repo: Optional[str],
    branch: Optional[str],
) -> Dict[str, Any]:
    """Run a named step via terminal_command and return an enriched result."""

    raw = await _tw().terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        owner=owner,
        repo=repo,
        branch=branch,
    )

    slim = _slim_terminal_command_payload(raw)
    exit_code = slim.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"
    stdout_tail = slim.get("stdout_tail") or ""
    stderr_tail = slim.get("stderr_tail") or ""
    missing_module = _extract_missing_module(stdout_tail, stderr_tail)
    cmd_not_found = _extract_command_not_found(stdout_tail, stderr_tail)

    step: Dict[str, Any] = {
        "name": name,
        "status": status,
        "summary": slim,
    }
    if missing_module:
        step["missing_module"] = missing_module
    if cmd_not_found:
        step["command_not_found_hint"] = cmd_not_found

    # Keep raw payload available for callers that need it.
    step["raw"] = raw
    return step


@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the project's test command in the persistent workspace and summarize the result."""

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 600)

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
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the lint or static-analysis command in the workspace."""

    timeout_seconds = _normalize_timeout_seconds(timeout_seconds, 600)

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
    timeout_seconds: float = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    lint_command: str = "ruff check .",
    format_command: Optional[str] = None,
    typecheck_command: Optional[str] = None,
    security_command: Optional[str] = None,
    preflight: bool = False,
    fail_fast: bool = True,
    include_raw_step_outputs: bool = False,
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
    logging happens at log/serialization boundaries.
    """

    timeout_seconds_i = _normalize_timeout_seconds(timeout_seconds, 600)

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
            "use_temp_venv": bool(use_temp_venv),
            "installing_dependencies": bool(installing_dependencies),
        },
    }

    controller_log: List[str] = [
        "Quality suite run:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
    ]
    steps: List[Dict[str, Any]] = []
    diagnostics: Dict[str, Any] = {}

    if preflight:
        controller_log.append("- Preflight: enabled")
        # Safe diagnostics only; avoid secrets.
        py = await _run_named_step(
            name="python_version",
            full_name=full_name,
            ref=ref,
            command="python --version",
            timeout_seconds=min(60, timeout_seconds_i),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=False,
            owner=owner,
            repo=repo,
            branch=branch,
        )
        pip = await _run_named_step(
            name="pip_version",
            full_name=full_name,
            ref=ref,
            command="python -m pip --version",
            timeout_seconds=min(60, timeout_seconds_i),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=False,
            owner=owner,
            repo=repo,
            branch=branch,
        )
        git_status = await _run_named_step(
            name="git_status",
            full_name=full_name,
            ref=ref,
            command="git status --porcelain",
            timeout_seconds=min(60, timeout_seconds_i),
            workdir=workdir,
            use_temp_venv=False,
            installing_dependencies=False,
            owner=owner,
            repo=repo,
            branch=branch,
        )

        # Keep preflight results in diagnostics, not in the main pass/fail flow.
        diagnostics["python_version"] = py.get("summary")
        diagnostics["pip_version"] = pip.get("summary")
        diagnostics["git_status"] = git_status.get("summary")
        steps.extend([py, pip, git_status])

    async def maybe_run_optional(
        name: str, command: Optional[str]
    ) -> Optional[Dict[str, Any]]:
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
            owner=owner,
            repo=repo,
            branch=branch,
        )
        return step

    # Optional steps (developer-controlled).
    fmt_step = await maybe_run_optional("format", format_command)
    if fmt_step is not None:
        steps.append(fmt_step)
        controller_log.append(f"- Format: {fmt_step.get('status')}")
        if fail_fast and fmt_step.get("status") == "failed":
            out = {
                "status": "failed",
                "suite": suite,
                "steps": _prune_raw_steps(steps, include_raw_step_outputs),
                "diagnostics": diagnostics,
                "controller_log": controller_log + ["- Aborted: format step failed"],
            }
            return out

    lint_step: Dict[str, Any]
    if lint_command:
        lint_step = await _run_named_step(
            name="lint",
            full_name=full_name,
            ref=ref,
            command=lint_command,
            timeout_seconds=timeout_seconds_i,
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            owner=owner,
            repo=repo,
            branch=branch,
        )
        steps.append(lint_step)
        controller_log.append(f"- Lint: {lint_step.get('status')}")

        if lint_step.get("status") == "failed" and lint_step.get("missing_module"):
            controller_log.append(
                f"- Hint: missing module '{lint_step.get('missing_module')}'. Consider installing dependencies (installing_dependencies=true)."
            )
        if lint_step.get("status") == "failed" and lint_step.get(
            "command_not_found_hint"
        ):
            controller_log.append(
                "- Hint: lint command not found. Ensure the tool is installed (or update lint_command)."
            )

        if fail_fast and lint_step.get("status") == "failed":
            # Back-compat: return the lint raw payload shape when possible.
            raw = lint_step.get("raw")
            if isinstance(raw, dict):
                raw.setdefault(
                    "controller_log", controller_log + ["- Aborted: lint failed"]
                )
                raw["suite"] = suite
                raw["steps"] = _prune_raw_steps(steps, include_raw_step_outputs)
                raw["diagnostics"] = diagnostics
                return raw
            return {
                "status": "failed",
                "suite": suite,
                "steps": _prune_raw_steps(steps, include_raw_step_outputs),
                "diagnostics": diagnostics,
                "controller_log": controller_log + ["- Aborted: lint failed"],
            }
    else:
        lint_step = {
            "name": "lint",
            "status": "skipped",
            "summary": {"command": None, "reason": "No lint_command provided"},
        }
        steps.append(lint_step)
        controller_log.append("- Lint: skipped (no lint_command provided)")

    type_step = await maybe_run_optional("typecheck", typecheck_command)
    if type_step is not None:
        steps.append(type_step)
        controller_log.append(f"- Typecheck: {type_step.get('status')}")
        if fail_fast and type_step.get("status") == "failed":
            return {
                "status": "failed",
                "suite": suite,
                "steps": _prune_raw_steps(steps, include_raw_step_outputs),
                "diagnostics": diagnostics,
                "controller_log": controller_log + ["- Aborted: typecheck failed"],
            }

    sec_step = await maybe_run_optional("security", security_command)
    if sec_step is not None:
        steps.append(sec_step)
        controller_log.append(f"- Security: {sec_step.get('status')}")
        if fail_fast and sec_step.get("status") == "failed":
            return {
                "status": "failed",
                "suite": suite,
                "steps": _prune_raw_steps(steps, include_raw_step_outputs),
                "diagnostics": diagnostics,
                "controller_log": controller_log + ["- Aborted: security step failed"],
            }

    tests_result = await run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds_i,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        owner=owner,
        repo=repo,
        branch=branch,
    )

    tests_status = tests_result.get("status") or "unknown"
    controller_log.append(f"- Tests: {tests_status}")

    # Always attach suite metadata + step summaries.
    overall_failed = any(
        step.get("status") == "failed"
        for step in steps
        if step.get("name") in {"format", "lint", "typecheck", "security"}
    )
    overall_status = (
        "failed" if (overall_failed or tests_status == "failed") else "passed"
    )

    if not fail_fast:
        return {
            "status": overall_status,
            "suite": suite,
            "lint": lint_step.get("raw"),
            "tests": tests_result,
            "steps": _prune_raw_steps(steps, include_raw_step_outputs),
            "diagnostics": diagnostics,
            "controller_log": controller_log,
        }

    # Back-compat: return tests_result as the primary shape, but enrich it.
    existing_log = tests_result.get("controller_log")
    if isinstance(existing_log, list) and existing_log:
        controller_log.extend(existing_log)
    tests_result["controller_log"] = controller_log
    tests_result["status"] = overall_status
    tests_result["suite"] = suite
    tests_result["steps"] = _prune_raw_steps(steps, include_raw_step_outputs)
    tests_result["diagnostics"] = diagnostics
    return tests_result


def _prune_raw_steps(
    steps: List[Dict[str, Any]], include_raw: bool
) -> List[Dict[str, Any]]:
    """Optionally drop raw payloads to keep the result lighter."""
    out: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        item = dict(step)
        if not include_raw:
            item.pop("raw", None)
        out.append(item)
    return out

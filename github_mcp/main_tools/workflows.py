from __future__ import annotations

import asyncio
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from github_mcp.exceptions import GitHubAPIError

from ._main import _main


async def list_workflow_runs(
    full_name: str,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List recent GitHub Actions workflow runs with optional filters."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    m = _main()

    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event

    return await m._github_request(
        "GET",
        f"/repos/{full_name}/actions/runs",
        params=params,
    )


async def list_recent_failures(
    full_name: str,
    branch: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """List recent failed or cancelled GitHub Actions workflow runs."""

    if limit <= 0:
        raise ValueError("limit must be > 0")

    m = _main()

    per_page = min(max(limit, 10), 50)

    runs_resp = await m.list_workflow_runs(
        full_name=full_name,
        branch=branch,
        per_page=per_page,
        page=1,
    )

    runs_json = runs_resp.get("json") or {}
    raw_runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []

    failure_conclusions = {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
    }

    failures: List[Dict[str, Any]] = []
    for run in raw_runs:
        status = run.get("status")
        conclusion = run.get("conclusion")

        if conclusion in failure_conclusions:
            include = True
        elif status == "completed" and conclusion not in (
            None,
            "success",
            "neutral",
            "skipped",
        ):
            include = True
        else:
            include = False

        if not include:
            continue

        failures.append(
            {
                "id": run.get("id"),
                "name": run.get("name"),
                "event": run.get("event"),
                "status": status,
                "conclusion": conclusion,
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "html_url": run.get("html_url"),
            }
        )

        if len(failures) >= limit:
            break

    return {
        "full_name": full_name,
        "branch": branch,
        "limit": limit,
        "runs": failures,
    }


async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    """Retrieve a specific workflow run including timing and conclusion."""

    m = _main()
    return await m._github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}",
    )


async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List jobs within a workflow run, useful for troubleshooting failures."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    m = _main()

    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params=params,
    )


async def get_workflow_run_overview(
    full_name: str,
    run_id: int,
    max_jobs: int = 500,
) -> Dict[str, Any]:
    """Summarize a GitHub Actions workflow run for CI triage.

 Aggregates run metadata, jobs (with pagination up to ``max_jobs``), failed
 jobs, and the longest jobs by duration.
 """

    if max_jobs <= 0:
        raise ValueError("max_jobs must be > 0")

    m = _main()

    run_resp = await m.get_workflow_run(full_name, run_id)
    run_json = run_resp.get("json") if isinstance(run_resp, dict) else run_resp
    if not isinstance(run_json, dict):
        run_json = {}

    run_summary: Dict[str, Any] = {
        "id": run_json.get("id"),
        "name": run_json.get("name"),
        "event": run_json.get("event"),
        "status": run_json.get("status"),
        "conclusion": run_json.get("conclusion"),
        "head_branch": run_json.get("head_branch"),
        "head_sha": run_json.get("head_sha"),
        "run_attempt": run_json.get("run_attempt"),
        "created_at": run_json.get("created_at"),
        "updated_at": run_json.get("updated_at"),
        "html_url": run_json.get("html_url"),
    }

    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None

    jobs: List[Dict[str, Any]] = []
    failed_jobs: List[Dict[str, Any]] = []
    jobs_with_duration: List[Dict[str, Any]] = []

    failure_conclusions = {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
    }

    per_page = 100
    page = 1
    fetched = 0
    last_page_job_ids: Optional[List[Any]] = None

    while fetched < max_jobs:
        remaining = max_jobs - fetched
        page_per_page = per_page if remaining >= per_page else remaining

        jobs_resp = await m.list_workflow_run_jobs(
            full_name, run_id, per_page=page_per_page, page=page
        )
        jobs_json = jobs_resp.get("json") or {}
        raw_jobs = jobs_json.get("jobs", []) if isinstance(jobs_json, dict) else []

        if not raw_jobs:
            break

        page_job_ids = [job.get("id") for job in raw_jobs if isinstance(job, dict)]
        if page_job_ids and last_page_job_ids is not None and page_job_ids == last_page_job_ids:
            break
        last_page_job_ids = page_job_ids

        for job in raw_jobs:
            if not isinstance(job, dict):
                continue

            status = job.get("status")
            conclusion = job.get("conclusion")
            started_at = job.get("started_at")
            completed_at = job.get("completed_at")

            start_dt = _parse_timestamp(started_at)
            end_dt = _parse_timestamp(completed_at)
            duration_seconds: Optional[float] = None
            if start_dt and end_dt:
                duration_seconds = max(0.0, (end_dt - start_dt).total_seconds())

            normalized = {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": status,
                "conclusion": conclusion,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_seconds": duration_seconds,
                "html_url": job.get("html_url"),
            }
            jobs.append(normalized)
            fetched += 1

            if duration_seconds is not None:
                jobs_with_duration.append(normalized)

            include_failure = False
            if conclusion in failure_conclusions:
                include_failure = True
            elif status == "completed" and conclusion not in (
                None,
                "success",
                "neutral",
                "skipped",
            ):
                include_failure = True
            if include_failure:
                failed_jobs.append(normalized)

            if fetched >= max_jobs:
                break

        if fetched >= max_jobs:
            break

        page += 1

    longest_jobs = sorted(
        jobs_with_duration,
        key=lambda j: j.get("duration_seconds") or 0.0,
        reverse=True,
    )[:5]

    summary_lines: list[str] = []

    status = run_summary.get("status") or "unknown"
    conclusion = run_summary.get("conclusion") or "unknown"
    name = run_summary.get("name") or str(run_summary.get("id") or run_id)

    summary_lines.append("Workflow run overview:")
    summary_lines.append(f"- Name: {name}")
    summary_lines.append(f"- Status: {status}")
    summary_lines.append(f"- Conclusion: {conclusion}")
    summary_lines.append(f"- Jobs: {len(jobs)} total, {len(failed_jobs)} failed")

    if longest_jobs:
        summary_lines.append("- Longest jobs by duration:")
        for job in longest_jobs:
            j_name = job.get("name") or job.get("id")
            dur = job.get("duration_seconds")
            if j_name is None or dur is None:
                continue
            summary_lines.append(f"  * {j_name}: {int(dur)}s")

    return {
        "full_name": full_name,
        "run_id": run_id,
        "run": run_summary,
        "jobs": jobs,
        "failed_jobs": failed_jobs,
        "longest_jobs": longest_jobs,
        "controller_log": summary_lines,
    }


async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job without truncation."""

    m = _main()

    client = getattr(m, "_http_client_github", None) or m._github_client_instance()
    request = client.build_request(
        "GET",
        f"/repos/{full_name}/actions/jobs/{job_id}/logs",
        headers={"Accept": "application/vnd.github+json"},
    )
    async with m._get_concurrency_semaphore():
        resp = await client.send(request, follow_redirects=True)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub job logs error {resp.status_code}: {resp.text}")

    content_type = resp.headers.get("Content-Type", "")
    if "zip" in content_type.lower():
        decode = getattr(m, "_decode_zipped_job_logs", None)
        logs = decode(resp.content) if callable(decode) else resp.text
    else:
        logs = resp.text

    return {
        "status_code": resp.status_code,
        "logs": logs,
        "content_type": content_type,
    }


async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: float = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """Poll a workflow run until completion or timeout."""

    m = _main()

    client = m._github_client_instance()
    loop = asyncio.get_running_loop()

    # Defensive parameter validation to avoid tight loops or negative timeouts
    try:
        timeout_seconds = int(timeout_seconds)
    except Exception:
        timeout_seconds = 900
    timeout_seconds = max(1, timeout_seconds)

    try:
        poll_interval_seconds = int(poll_interval_seconds)
    except Exception:
        poll_interval_seconds = 10
    poll_interval_seconds = max(1, poll_interval_seconds)

    end_time = loop.time() + timeout_seconds

    while True:
        async with m._get_concurrency_semaphore():
            resp = await client.get(
                f"/repos/{full_name}/actions/runs/{run_id}",
            )
        if resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub workflow run error {resp.status_code}: {resp.text}")

        data = resp.json()
        status = data.get("status")
        conclusion = data.get("conclusion")

        if status == "completed":
            summary_lines = [
                "Workflow run finished:",
                f"- Status: {status}",
                f"- Conclusion: {conclusion}",
            ]
            return {
                "status": status,
                "conclusion": conclusion,
                "run": data,
                "controller_log": summary_lines,
            }

        if loop.time() > end_time:
            summary_lines = [
                "Workflow run timed out while waiting for completion:",
                f"- Last known status: {status}",
                f"- Last known conclusion: {conclusion}",
                f"- Timeout seconds: {timeout_seconds}",
            ]
            return {
                "status": status,
                "timeout": True,
                "run": data,
                "controller_log": summary_lines,
            }

        await asyncio.sleep(poll_interval_seconds)


async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trigger a workflow dispatch event on the given ref."""

    m = _main()

    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs

    client = m._github_client_instance()
    async with m._get_concurrency_semaphore():
        resp = await client.post(
            f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
            json=payload,
        )
    if resp.status_code not in (204, 201):
        raise GitHubAPIError(f"GitHub workflow dispatch error {resp.status_code}: {resp.text}")

    summary_lines = [
        "Triggered workflow dispatch:",
        f"- Repo: {full_name}",
        f"- Workflow: {workflow}",
        f"- Ref: {ref}",
    ]
    if inputs:
        summary_lines.append(f"- Inputs keys: {sorted(inputs.keys())}")

    return {
        "status_code": resp.status_code,
        "controller_log": summary_lines,
    }


async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """Trigger a workflow and block until it completes or hits timeout."""

    m = _main()

    await trigger_workflow_dispatch(full_name, workflow, ref, inputs)

    # The dispatch API does not return a run id. Poll for the run we just triggered.
    dispatched_at = datetime.now(timezone.utc)

    # Branch filter only works for branch names. For tags/SHAs we must query without the branch param.
    ref_str = (ref or "").strip()
    is_sha = len(ref_str) == 40 and all(c in string.hexdigits for c in ref_str)
    branch_filter: Optional[str] = None if is_sha else ref

    poll_deadline = asyncio.get_running_loop().time() + 60
    run_id: Optional[int] = None

    while asyncio.get_running_loop().time() < poll_deadline and run_id is None:
        runs = await m.list_workflow_runs(
            full_name=full_name,
            branch=branch_filter,
            event="workflow_dispatch",
            per_page=30,
            page=1,
        )
        workflow_runs = runs.get("json", {}).get("workflow_runs", [])

        # Prefer runs created after we dispatched (allow small clock skew).
        cutoff = dispatched_at - timedelta(seconds=10)

        def _parse_created(value: Any) -> Optional[datetime]:
            if not isinstance(value, str):
                return None
            try:
                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                return None

        candidates: List[Dict[str, Any]] = []
        for run in workflow_runs or []:
            if not isinstance(run, dict):
                continue
            if run.get("event") != "workflow_dispatch":
                continue

            # Ensure this is the workflow we triggered.
            path = run.get("path") or ""
            if workflow.endswith((".yml", ".yaml")) and path and path != workflow:
                continue

            created_at = _parse_created(run.get("created_at"))
            if created_at is not None and created_at < cutoff:
                continue

            # If a branch filter is used, head_branch should match. Otherwise, fall back to ref match.
            if branch_filter and run.get("head_branch") not in (None, branch_filter):
                continue

            candidates.append(run)

        if candidates:
            # Pick the most recent matching run.
            candidates.sort(
                key=lambda r: _parse_created(r.get("created_at"))
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            run_id = candidates[0].get("id")
            break

        await asyncio.sleep(2)

    if run_id is None:
        raise GitHubAPIError("No matching workflow run found after dispatch")

    result = await wait_for_workflow_run(
        full_name,
        run_id,
        timeout_seconds,
        poll_interval_seconds,
    )

    summary_lines = [
        "Triggered workflow and waited for completion:",
        f"- Repo: {full_name}",
        f"- Workflow: {workflow}",
        f"- Ref: {ref}",
        f"- Run ID: {run_id}",
    ]
    result_log = result.get("controller_log")
    if isinstance(result_log, list):
        summary_lines.extend(result_log)

    return {
        "run_id": run_id,
        "result": result,
        "controller_log": summary_lines,
    }

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ._main import _main


async def create_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Create a new branch from a base ref."""

    m = _main()

    branch = branch.strip()
    if not branch:
        raise ValueError("branch must be non-empty")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
        raise ValueError("branch contains invalid characters")
    if ".." in branch or "@{" in branch:
        raise ValueError("branch contains invalid ref sequence")
    if branch.startswith("/") or branch.endswith("/"):
        raise ValueError("branch must not start or end with '/'")
    if branch.endswith(".lock"):
        raise ValueError("branch must not end with '.lock'")

    base_ref = m._effective_ref_for_repo(full_name, from_ref)

    client = m._github_client_instance()

    base_sha: Optional[str] = None
    async with m._get_concurrency_semaphore():
        resp = await client.get(f"/repos/{full_name}/git/ref/heads/{base_ref}")
    if resp.status_code == 200:
        payload = resp.json() if hasattr(resp, "json") else {}
        obj = payload.get("object") if isinstance(payload, dict) else None
        if isinstance(obj, dict):
            base_sha = obj.get("sha")
    elif resp.status_code == 404:
        async with m._get_concurrency_semaphore():
            tag_resp = await client.get(f"/repos/{full_name}/git/ref/tags/{base_ref}")
        if tag_resp.status_code == 200:
            payload = tag_resp.json() if hasattr(tag_resp, "json") else {}
            obj = payload.get("object") if isinstance(payload, dict) else None
            if isinstance(obj, dict):
                base_sha = obj.get("sha")
    else:
        raise m.GitHubAPIError(
            f"GitHub create_branch base ref error {resp.status_code}: {resp.text}"
        )

    if base_sha is None:
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", from_ref.strip()):
            base_sha = from_ref.strip()
        else:
            raise m.GitHubAPIError(f"Unable to resolve base ref {from_ref!r} in {full_name}")

    new_ref = f"refs/heads/{branch}"
    body = {"ref": new_ref, "sha": base_sha}

    async with m._get_concurrency_semaphore():
        create_resp = await client.post(f"/repos/{full_name}/git/refs", json=body)

    if create_resp.status_code == 201:
        return {"status_code": create_resp.status_code, "json": create_resp.json()}

    raise m.GitHubAPIError(
        f"GitHub create_branch error {create_resp.status_code}: {create_resp.text}"
    )


async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Idempotently ensure a branch exists, creating it from ``from_ref``."""

    m = _main()

    client = m._github_client_instance()
    async with m._get_concurrency_semaphore():
        resp = await client.get(f"/repos/{full_name}/git/ref/heads/{branch}")
    if resp.status_code == 404:
        return await create_branch(full_name, branch, from_ref)
    if resp.status_code >= 400:
        raise m.GitHubAPIError(f"GitHub ensure_branch error {resp.status_code}: {resp.text}")
    return {"status_code": resp.status_code, "json": resp.json()}


async def get_branch_summary(full_name: str, branch: str, base: str = "main") -> Dict[str, Any]:
    """Return PRs and latest workflow run for a branch."""

    m = _main()

    effective_branch = m._effective_ref_for_repo(full_name, branch)
    effective_base = m._effective_ref_for_repo(full_name, base)

    compare_error: Optional[str] = None

    owner: Optional[str] = None
    if "/" in full_name:
        owner = full_name.split("/", 1)[0]
    head_param = f"{owner}:{effective_branch}" if owner else None

    async def _safe_list_prs(state: str) -> Dict[str, Any]:
        try:
            return await m.list_pull_requests(
                full_name, state=state, head=head_param, base=effective_base
            )
        except Exception as exc:  # pragma: no cover
            return {"error": str(exc), "json": []}

    open_prs_resp = await _safe_list_prs("open")
    closed_prs_resp = await _safe_list_prs("closed")

    open_prs = open_prs_resp.get("json") or []
    closed_prs = closed_prs_resp.get("json") or []

    workflow_error: Optional[str] = None
    latest_workflow_run: Optional[Dict[str, Any]] = None
    try:
        runs_resp = await m.list_workflow_runs(full_name, branch=effective_branch, per_page=1)
        runs_json = runs_resp.get("json") or {}
        runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []
        if runs:
            latest_workflow_run = runs[0]
    except Exception as exc:
        workflow_error = str(exc)

    return {
        "full_name": full_name,
        "branch": effective_branch,
        "base": effective_base,
        "compare_error": compare_error,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
        "latest_workflow_run": latest_workflow_run,
        "workflow_error": workflow_error,
    }


async def get_latest_branch_status(
    full_name: str, branch: str, base: str = "main"
) -> Dict[str, Any]:
    """Return normalized status for a branch (PRs + latest workflow)."""

    m = _main()

    summary = await get_branch_summary(full_name=full_name, branch=branch, base=base)
    normalizer = getattr(m, "_normalize_branch_summary", None)
    if callable(normalizer):
        return normalizer(summary)
    return summary

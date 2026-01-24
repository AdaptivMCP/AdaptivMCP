from __future__ import annotations

from typing import Any

from github_mcp.utils import _normalize_repo_path_for_repo

from ._main import _main


async def get_repo_dashboard(
    full_name: str, branch: str | None = None
) -> dict[str, Any]:
    """Return a compact, multi-signal dashboard for a repository.

    Implementation moved out of `main.py` to keep the main registration surface
    small and navigable.

    This is intentionally read-only: it aggregates several lower-level calls and
    degrades gracefully (each section has a corresponding *_error field).
    """

    m = _main()

    # Resolve the effective branch using the same helper as other tools.
    if branch is None:
        # Fall back to the default branch when available.
        defaults = await m.get_repo_defaults(full_name)
        repo_defaults = defaults.get("defaults") or {}
        effective_branch = repo_defaults.get(
            "default_branch"
        ) or m._effective_ref_for_repo(
            full_name,
            "main",
        )
    else:
        effective_branch = m._effective_ref_for_repo(full_name, branch)

    # --- Repository metadata ---
    repo_info: dict[str, Any] | None = None
    repo_error: str | None = None
    try:
        repo_resp = await m.get_repository(full_name)
        repo_info = repo_resp.get("json") or {}
    except Exception as exc:  # pragma: no cover - defensive
        repo_error = str(exc)

    # --- Open pull requests (small window) ---
    pr_error: str | None = None
    open_prs: list[dict[str, Any]] = []
    try:
        pr_resp = await m.list_pull_requests(
            full_name,
            state="open",
            per_page=10,
            page=1,
        )
        open_prs = pr_resp.get("json") or []
    except Exception as exc:  # pragma: no cover - defensive
        pr_error = str(exc)

    # --- Open issues (excluding PRs) ---
    issues_error: str | None = None
    open_issues: list[dict[str, Any]] = []
    try:
        issues_resp = await m.list_repository_issues(
            full_name,
            state="open",
            per_page=10,
            page=1,
        )
        raw_issues = issues_resp.get("json") or []
        # Filter out pull requests that show up in the issues API.
        for item in raw_issues:
            if isinstance(item, dict) and "pull_request" not in item:
                open_issues.append(item)
    except Exception as exc:  # pragma: no cover - defensive
        issues_error = str(exc)

    # --- Recent workflow runs on this branch ---
    workflows_error: str | None = None
    workflow_runs: list[dict[str, Any]] = []
    try:
        runs_resp = await m.list_workflow_runs(
            full_name,
            branch=effective_branch,
            per_page=5,
            page=1,
        )
        runs_json = runs_resp.get("json") or {}
        workflow_runs = (
            runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []
        )
    except Exception as exc:  # pragma: no cover - defensive
        workflows_error = str(exc)

    # --- Top-level tree entries on the branch ---
    tree_error: str | None = None
    top_level_tree: list[dict[str, Any]] = []
    try:
        tree_resp = await m.list_repository_tree(
            full_name,
            ref=effective_branch,
            recursive=False,
            max_entries=200,
        )
        entries = tree_resp.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            # Normalize paths defensively (e.g., strip accidental GitHub URLs).
            normalized_path = _normalize_repo_path_for_repo(full_name, path)

            # Keep only top-level entries (no slashes) for a compact view.
            if not normalized_path or "/" in normalized_path:
                continue

            top_level_tree.append(
                {
                    "path": normalized_path,
                    "type": entry.get("type"),
                    "size": entry.get("size"),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        tree_error = str(exc)

    return {
        "branch": effective_branch,
        "repo": repo_info,
        "repo_error": repo_error,
        "pull_requests": open_prs,
        "pull_requests_error": pr_error,
        "issues": open_issues,
        "issues_error": issues_error,
        "workflows": workflow_runs,
        "workflows_error": workflows_error,
        "top_level_tree": top_level_tree,
        "top_level_tree_error": tree_error,
    }

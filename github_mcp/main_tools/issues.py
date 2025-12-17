"""Issue tools and issue context helpers.

Tool implementations for the main MCP surface.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from ._main import _main


async def list_recent_issues(
    filter: str = "assigned",
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """Return recent issues the user can access (includes PRs)."""

    m = _main()

    params = {"filter": filter, "state": state, "per_page": per_page, "page": page}
    return await m._github_request("GET", "/issues", params=params)


async def list_repository_issues(
    full_name: str,
    state: str = "open",
    labels: Optional[List[str]] = None,
    assignee: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List issues for a specific repository (includes PRs)."""

    m = _main()

    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if labels:
        params["labels"] = ",".join(labels)
    if assignee is not None:
        params["assignee"] = assignee

    return await m._github_request("GET", f"/repos/{full_name}/issues", params=params)


async def fetch_issue(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Fetch a GitHub issue."""

    m = _main()
    return await m._github_request("GET", f"/repos/{full_name}/issues/{issue_number}")


async def fetch_issue_comments(
    full_name: str, issue_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch comments for a GitHub issue."""

    m = _main()

    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET",
        f"/repos/{full_name}/issues/{issue_number}/comments",
        params=params,
    )


async def get_issue_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch reactions for an issue comment."""

    m = _main()

    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET",
        f"/repos/{full_name}/issues/comments/{comment_id}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


async def create_issue(
    full_name: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a GitHub issue in the given repository."""

    m = _main()

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    m._ensure_write_allowed(f"create issue in {full_name}: {title!r}")

    payload: Dict[str, Any] = {"title": title}
    if body is not None:
        payload["body"] = body
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees

    return await m._github_request(
        "POST",
        f"/repos/{full_name}/issues",
        json_body=payload,
    )


async def update_issue(
    full_name: str,
    issue_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[Literal["open", "closed"]] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update fields on an existing GitHub issue."""

    m = _main()

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    m._ensure_write_allowed(f"update issue #{issue_number} in {full_name}")

    payload: Dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        allowed_states = {"open", "closed"}
        if state not in allowed_states:
            raise ValueError("state must be 'open' or 'closed'")
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees

    if not payload:
        raise ValueError("At least one field must be provided to update_issue")

    return await m._github_request(
        "PATCH",
        f"/repos/{full_name}/issues/{issue_number}",
        json_body=payload,
    )


async def comment_on_issue(
    full_name: str,
    issue_number: int,
    body: str,
) -> Dict[str, Any]:
    """Post a comment on an issue."""

    m = _main()

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    m._ensure_write_allowed(f"comment on issue #{issue_number} in {full_name}")

    return await m._github_request(
        "POST",
        f"/repos/{full_name}/issues/{issue_number}/comments",
        json_body={"body": body},
    )


async def open_issue_context(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Return an issue plus related branches and pull requests."""

    m = _main()

    issue_resp = await m.fetch_issue(full_name, issue_number)
    issue_json = issue_resp.get("json") if isinstance(issue_resp, dict) else issue_resp

    branches_resp = await m.list_branches(full_name, per_page=100)
    branches_json = branches_resp.get("json") or []
    branch_names = [b.get("name") for b in branches_json if isinstance(b, dict)]

    pattern = re.compile(rf"(?i)(?:^|[-_/]){re.escape(str(issue_number))}(?:$|[-_/])")
    candidate_branches = [
        name for name in branch_names if isinstance(name, str) and pattern.search(name)
    ]

    prs_resp = await m.list_pull_requests(full_name, state="all")
    prs = prs_resp.get("json") or []

    issue_str = str(issue_number)
    open_prs: List[Dict[str, Any]] = []
    closed_prs: List[Dict[str, Any]] = []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        branch_name = pr.get("head", {}).get("ref")
        text = f"{pr.get('title', '')}\n{pr.get('body', '')}"
        if issue_str in text or (isinstance(branch_name, str) and issue_str in branch_name):
            target_list = open_prs if pr.get("state") == "open" else closed_prs
            target_list.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft"),
                    "html_url": pr.get("html_url"),
                    "head": pr.get("head"),
                    "base": pr.get("base"),
                }
            )

    return {
        "issue": issue_json,
        "candidate_branches": candidate_branches,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
    }


async def get_issue_overview(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Summarize a GitHub issue for navigation and planning.

    This helper is intentionally read-only.
    It is designed for assistants to call before doing any write work so
    they understand the current state of an issue.
    """

    m = _main()

    # Reuse the richer context helper so we see branches / PRs / labels, etc.
    context = await m.open_issue_context(full_name=full_name, issue_number=issue_number)
    issue = context.get("issue") or {}
    if not isinstance(issue, dict):
        issue = {}

    def _normalize_labels(raw: Any) -> List[Dict[str, Any]]:
        labels: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    labels.append(
                        {
                            "name": str(item.get("name", "")),
                            "color": item.get("color"),
                        }
                    )
                elif isinstance(item, str):
                    labels.append({"name": item})
        return labels

    def _normalize_user(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        login = raw.get("login")
        if not isinstance(login, str):
            return None
        return {"login": login, "html_url": raw.get("html_url")}

    def _normalize_assignees(raw: Any) -> List[Dict[str, Any]]:
        assignees: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for user in raw:
                normalized = _normalize_user(user)
                if normalized is not None:
                    assignees.append(normalized)
        return assignees

    # Core issue fields
    normalized_issue: Dict[str, Any] = {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "html_url": issue.get("html_url"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "user": _normalize_user(issue.get("user")),
        "assignees": _normalize_assignees(issue.get("assignees")),
        "labels": _normalize_labels(issue.get("labels")),
    }

    body_text = issue.get("body") or ""

    def _extract_checklist_items(text: str, source: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.lstrip()
            if line.startswith("- [ ") or line.startswith("- [") or line.startswith("* ["):
                checked = "[x]" in line.lower() or "[X]" in line
                # Strip the leading marker (e.g. "- [ ]" / "- [x]")
                after = line.split("]", 1)
                description = after[1].strip() if len(after) > 1 else raw_line.strip()
                if description:
                    items.append(
                        {
                            "text": description,
                            "checked": bool(checked),
                            "source": source,
                        }
                    )
        return items

    checklist_items: List[Dict[str, Any]] = []
    if body_text:
        checklist_items.extend(_extract_checklist_items(body_text, source="issue_body"))

    # Pull checklist items from comments as well, if available.
    comments = context.get("comments")
    if isinstance(comments, list):
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            body = comment.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            checklist_items.extend(_extract_checklist_items(body, source="comment"))

    # Related branches / PRs are already computed by open_issue_context.
    candidate_branches = context.get("candidate_branches") or []
    open_prs = context.get("open_prs") or []
    closed_prs = context.get("closed_prs") or []

    return {
        "issue": normalized_issue,
        "candidate_branches": candidate_branches,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
        "checklist_items": checklist_items,
    }

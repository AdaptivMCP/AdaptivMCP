"""Argument normalization helpers and safety checks.

Tool implementations for the main MCP surface.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def normalize_issue_payload(raw_issue: Any) -> Optional[Dict[str, Any]]:
    """Normalize issue payloads returned by GitHub APIs into a compact shape."""

    issue = raw_issue
    if isinstance(raw_issue, dict) and "json" in raw_issue:
        issue = raw_issue.get("json")
    if not isinstance(issue, dict):
        return None

    user = issue.get("user") if isinstance(issue.get("user"), dict) else None
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []

    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "html_url": issue.get("html_url"),
        "user": user.get("login") if user else None,
        "labels": [lbl.get("name") for lbl in labels if isinstance(lbl, dict)],
    }


def normalize_pr_payload(raw_pr: Any) -> Optional[Dict[str, Any]]:
    """Normalize PR payloads returned by GitHub APIs into a compact shape."""

    pr = raw_pr
    if isinstance(raw_pr, dict) and "json" in raw_pr:
        pr = raw_pr.get("json")
    if not isinstance(pr, dict):
        return None

    user = pr.get("user") if isinstance(pr.get("user"), dict) else None
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}

    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "merged": pr.get("merged"),
        "html_url": pr.get("html_url"),
        "user": user.get("login") if user else None,
        "head_ref": head.get("ref"),
        "base_ref": base.get("ref"),
    }


def normalize_branch_summary(summary: Any) -> Optional[Dict[str, Any]]:
    """Normalize get_branch_summary output into a compact shape.

    Diff/compare data has been removed from the server; this helper focuses on PRs
    and CI signals.
    """

    if not isinstance(summary, dict):
        return None

    def _simplify_prs(prs: Any) -> list[Dict[str, Any]]:
        simplified: list[Dict[str, Any]] = []
        if not isinstance(prs, list):
            return simplified
        for pr in prs:
            if not isinstance(pr, dict):
                continue
            head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
            base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
            simplified.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft"),
                    "html_url": pr.get("html_url"),
                    "head_ref": head.get("ref"),
                    "base_ref": base.get("ref"),
                }
            )
        return simplified

    latest_run = summary.get("latest_workflow_run")
    latest_run_normalized = None
    if isinstance(latest_run, dict):
        latest_run_normalized = {
            "id": latest_run.get("id"),
            "status": latest_run.get("status"),
            "conclusion": latest_run.get("conclusion"),
            "html_url": latest_run.get("html_url"),
            "head_branch": latest_run.get("head_branch"),
        }

    normalized = {
        "branch": summary.get("branch"),
        "base": summary.get("base"),
        "open_prs": _simplify_prs(summary.get("open_prs")),
        "closed_prs": _simplify_prs(summary.get("closed_prs")),
        "latest_workflow_run": latest_run_normalized,
    }

    if all(value is None or value == [] for value in normalized.values()):
        return None

    return normalized

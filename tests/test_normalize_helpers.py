from __future__ import annotations

from github_mcp.main_tools.normalize import (
    normalize_branch_summary,
    normalize_issue_payload,
    normalize_pr_payload,
)


def test_normalize_issue_payload_handles_wrapped_and_malformed_inputs() -> None:
    assert normalize_issue_payload(None) is None
    assert normalize_issue_payload([1, 2, 3]) is None

    raw = {
        "json": {
            "number": 1,
            "title": "Bug",
            "state": "open",
            "html_url": "https://example/1",
            "user": {"login": "alice"},
            "labels": [{"name": "triage"}, "not-a-dict"],
        }
    }

    assert normalize_issue_payload(raw) == {
        "number": 1,
        "title": "Bug",
        "state": "open",
        "html_url": "https://example/1",
        "user": "alice",
        "labels": ["triage"],
    }


def test_normalize_pr_payload_handles_wrapped_and_missing_nested_fields() -> None:
    assert normalize_pr_payload("nope") is None

    raw = {
        "json": {
            "number": 2,
            "title": "Feature",
            "state": "closed",
            "draft": False,
            "merged": True,
            "html_url": "https://example/2",
            "user": "not-a-dict",
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        }
    }

    assert normalize_pr_payload(raw) == {
        "number": 2,
        "title": "Feature",
        "state": "closed",
        "draft": False,
        "merged": True,
        "html_url": "https://example/2",
        "user": None,
        "head_ref": "feature",
        "base_ref": "main",
    }


def test_normalize_branch_summary_handles_empty_and_partial_shapes() -> None:
    assert normalize_branch_summary(None) is None
    assert normalize_branch_summary({"branch": None, "base": None}) is None

    summary = {
        "branch": "feature",
        "base": "main",
        "open_prs": [
            {
                "number": 5,
                "title": "PR",
                "state": "open",
                "draft": False,
                "html_url": "https://example/pr/5",
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
            },
            "not-a-dict",
        ],
        "closed_prs": "not-a-list",
        "latest_workflow_run": "not-a-dict",
    }

    assert normalize_branch_summary(summary) == {
        "branch": "feature",
        "base": "main",
        "open_prs": [
            {
                "number": 5,
                "title": "PR",
                "state": "open",
                "draft": False,
                "html_url": "https://example/pr/5",
                "head_ref": "feature",
                "base_ref": "main",
            }
        ],
        "closed_prs": [],
        "latest_workflow_run": None,
    }

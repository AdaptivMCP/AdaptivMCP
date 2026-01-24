from __future__ import annotations

from typing import Any

import pytest

from github_mcp.main_tools import pull_requests


def _make_structured_422(message: str, *, error_entry_message: str) -> dict[str, Any]:
    return {
        "json": {},
        "error": {
            "message": f"GitHub API error 422: {message}",
        },
        "raw_response": {
            "status_code": 422,
            "json": {
                "message": "Validation Failed",
                "errors": [
                    {
                        "resource": "PullRequest",
                        "code": "custom",
                        "message": error_entry_message,
                    }
                ],
            },
        },
    }


@pytest.mark.anyio
async def test_open_pr_for_existing_branch_returns_noop_on_no_commits(
    monkeypatch: pytest.MonkeyPatch,
):
    import main as main_mod

    monkeypatch.setattr(
        main_mod,
        "_effective_ref_for_repo",
        lambda _full_name, base: base,
        raising=False,
    )

    async def fake_create_pull_request(**_kwargs: Any) -> dict[str, Any]:
        return _make_structured_422(
            "Validation Failed",
            error_entry_message="No commits between main and feature/test",
        )

    async def fake_list_pull_requests(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"json": []}

    monkeypatch.setattr(pull_requests, "create_pull_request", fake_create_pull_request)
    monkeypatch.setattr(
        main_mod, "list_pull_requests", fake_list_pull_requests, raising=False
    )

    result = await pull_requests.open_pr_for_existing_branch(
        full_name="octo-org/octo-repo",
        branch="feature/test",
        base="main",
        title="noop test",
        body="body",
        draft=False,
    )

    assert result["status"] == "ok"
    assert result.get("noop") is True
    assert result.get("reason") == "no_commits_between_branches"


@pytest.mark.anyio
async def test_open_pr_for_existing_branch_reuses_existing_pr_on_conflict(
    monkeypatch: pytest.MonkeyPatch,
):
    import main as main_mod

    monkeypatch.setattr(
        main_mod,
        "_effective_ref_for_repo",
        lambda _full_name, base: base,
        raising=False,
    )

    async def fake_create_pull_request(**_kwargs: Any) -> dict[str, Any]:
        return _make_structured_422(
            "Validation Failed",
            error_entry_message="A pull request already exists for octo-org:feature/test",
        )

    async def fake_list_pull_requests(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        # Ensure the list filter is correctly constructed.
        assert kwargs.get("head") == "octo-org:feature/test"
        assert kwargs.get("base") == "main"
        return {
            "json": [
                {
                    "number": 42,
                    "html_url": "https://example.invalid/pull/42",
                }
            ]
        }

    monkeypatch.setattr(pull_requests, "create_pull_request", fake_create_pull_request)
    monkeypatch.setattr(
        main_mod, "list_pull_requests", fake_list_pull_requests, raising=False
    )

    result = await pull_requests.open_pr_for_existing_branch(
        full_name="octo-org/octo-repo",
        branch="feature/test",
        base="main",
        title="conflict test",
        body="body",
        draft=False,
    )

    assert result["status"] == "ok"
    assert result.get("reused_existing") is True
    assert result.get("pr_number") == 42
    assert result.get("pr_url") == "https://example.invalid/pull/42"

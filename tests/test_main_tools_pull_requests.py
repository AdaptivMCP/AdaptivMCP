from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class StructuredError(Exception):
    context: str
    path: str | None = None


class FakeMain:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []
        self._github_request_calls: list[
            tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

        # Queues for high-level helpers used by pull_requests.
        self.ensure_branch_calls: list[tuple[str, str, str]] = []
        self.resolve_sha_calls: list[tuple[str, str, str]] = []
        self.commit_calls: list[dict[str, Any]] = []
        self.verify_calls: list[tuple[str, str, str]] = []

        self.fetch_pr_calls: list[tuple[str, int]] = []
        self.list_pr_files_calls: list[tuple[str, int, int]] = []
        self.status_calls: list[tuple[str, str]] = []
        self.list_runs_calls: list[dict[str, Any]] = []
        self.list_pull_requests_calls: list[dict[str, Any]] = []

        self._queue_fetch_pr: list[dict[str, Any]] = []
        self._queue_list_files: list[dict[str, Any]] = []
        self._queue_status: list[dict[str, Any]] = []
        self._queue_runs: list[dict[str, Any]] = []
        self._queue_list_prs: list[dict[str, Any]] = []

        self.normalize_calls: list[dict[str, Any]] = []

    # --- Minimal surfaces used by module ---

    def _effective_ref_for_repo(self, _full_name: str, base: str) -> str:
        return f"effective-{base}"  # make normalization visible

    def _structured_tool_error(
        self, exc: Exception, *, context: str, path: str | None = None
    ):
        return {
            "status": "error",
            "ok": False,
            "context": context,
            "path": path,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    async def _github_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._github_request_calls.append((method, path, params, json_body))
        return {
            "method": method,
            "path": path,
            "params": params,
            "json_body": json_body,
            "json": {},
        }

    async def ensure_branch(self, full_name: str, branch: str, from_ref: str = "main"):
        self.ensure_branch_calls.append((full_name, branch, from_ref))
        return {"status": "ok"}

    async def _load_body_from_content_url(self, content_url: str, context: str):
        self.calls.append(
            ("load_body", {"content_url": content_url, "context": context})
        )
        return b"from-url"

    async def _resolve_file_sha(self, full_name: str, path: str, branch: str):
        self.resolve_sha_calls.append((full_name, path, branch))
        return "sha-existing"

    async def _perform_github_commit(
        self,
        *,
        full_name: str,
        path: str,
        message: str,
        branch: str,
        body_bytes: bytes,
        sha: str | None,
    ):
        self.commit_calls.append(
            {
                "full_name": full_name,
                "path": path,
                "message": message,
                "branch": branch,
                "body_bytes": body_bytes,
                "sha": sha,
            }
        )
        return {"ok": True, "path": path}

    async def _verify_file_on_branch(self, full_name: str, path: str, branch: str):
        self.verify_calls.append((full_name, path, branch))
        return {"verified": True, "path": path, "branch": branch}

    async def fetch_pr(self, full_name: str, pull_number: int) -> dict[str, Any]:
        self.fetch_pr_calls.append((full_name, pull_number))
        if self._queue_fetch_pr:
            return self._queue_fetch_pr.pop(0)
        return {"json": {}}

    async def list_pr_changed_filenames(
        self, full_name: str, pull_number: int, per_page: int = 100, page: int = 1
    ):
        self.list_pr_files_calls.append((full_name, pull_number, per_page))
        if self._queue_list_files:
            return self._queue_list_files.pop(0)
        return {"json": []}

    async def get_commit_combined_status(
        self, full_name: str, ref: str
    ) -> dict[str, Any]:
        self.status_calls.append((full_name, ref))
        if self._queue_status:
            return self._queue_status.pop(0)
        return {"json": {"state": "success"}}

    async def list_workflow_runs(
        self,
        full_name: str,
        branch: str | None = None,
        status: str | None = None,
        event: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ):
        self.list_runs_calls.append(
            {
                "full_name": full_name,
                "branch": branch,
                "status": status,
                "event": event,
                "per_page": per_page,
                "page": page,
            }
        )
        if self._queue_runs:
            return self._queue_runs.pop(0)
        return {"json": {"workflow_runs": []}}

    async def list_pull_requests(self, **kwargs):
        self.list_pull_requests_calls.append(kwargs)
        if self._queue_list_prs:
            return self._queue_list_prs.pop(0)
        return {"json": []}

    def _normalize_pr_payload(self, pr: dict[str, Any]) -> dict[str, Any] | None:
        self.normalize_calls.append(pr)
        # Drop PRs that don't have a number.
        if pr.get("number") is None:
            return None
        return {"number": pr.get("number"), "html_url": pr.get("html_url")}


def _install_main(monkeypatch: pytest.MonkeyPatch, module, fake: FakeMain):
    monkeypatch.setattr(module, "_main", lambda: fake)


@pytest.mark.asyncio
async def test_head_helpers_normalize_and_parse():
    from github_mcp.main_tools import pull_requests

    assert pull_requests._strip_heads_prefix("refs/heads/feat") == "feat"
    assert pull_requests._strip_heads_prefix("heads/feat") == "feat"
    assert pull_requests._strip_heads_prefix(" feat ") == "feat"

    assert pull_requests._parse_head_ref("branch") == (None, "branch")
    assert pull_requests._parse_head_ref("octo:branch") == ("octo", "branch")
    assert pull_requests._parse_head_ref("octo:refs/heads/branch") == ("octo", "branch")

    assert pull_requests._head_for_api("octo:heads/branch") == "octo:branch"
    assert pull_requests._head_for_api("refs/heads/branch") == "branch"
    assert pull_requests._head_branch_only("octo:refs/heads/branch") == "branch"


@pytest.mark.asyncio
async def test_list_pull_requests_validates_and_builds_params(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    out = await pull_requests.list_pull_requests(
        "o/r", state="open", head="octo:feat", base="main", per_page=5, page=2
    )

    assert out["path"] == "/repos/o/r/pulls"
    assert fake._github_request_calls == [
        (
            "GET",
            "/repos/o/r/pulls",
            {
                "state": "open",
                "per_page": 5,
                "page": 2,
                "head": "octo:feat",
                "base": "main",
            },
            None,
        )
    ]

    with pytest.raises(ValueError):
        await pull_requests.list_pull_requests("o/r", state="wat")
    with pytest.raises(ValueError):
        await pull_requests.list_pull_requests("o/r", per_page=0)
    with pytest.raises(ValueError):
        await pull_requests.list_pull_requests("o/r", page=0)


@pytest.mark.asyncio
async def test_merge_pull_request_payload(monkeypatch: pytest.MonkeyPatch):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    await pull_requests.merge_pull_request(
        "o/r", 7, merge_method="rebase", commit_title="t", commit_message=None
    )

    assert fake._github_request_calls[-1] == (
        "PUT",
        "/repos/o/r/pulls/7/merge",
        None,
        {"merge_method": "rebase", "commit_title": "t"},
    )

    with pytest.raises(ValueError):
        await pull_requests.merge_pull_request("o/r", 7, merge_method="invalid")


@pytest.mark.asyncio
async def test_get_pr_info_extracts_summary(monkeypatch: pytest.MonkeyPatch):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    async def _fake_fetch(_full: str, _num: int):
        return {
            "status_code": 200,
            "json": {
                "title": "T",
                "state": "open",
                "draft": False,
                "merged": False,
                "user": {"login": "octo"},
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
            },
        }

    monkeypatch.setattr(pull_requests, "fetch_pr", _fake_fetch)

    out = await pull_requests.get_pr_info("o/r", 1)
    assert out["summary"]["user"] == "octo"
    assert out["summary"]["head"] == "feature"
    assert out["summary"]["base"] == "main"

    # Non-dict JSON yields summary=None.
    async def _fake_fetch_bad(_full: str, _num: int):
        return {"status_code": 200, "json": ["nope"]}

    monkeypatch.setattr(pull_requests, "fetch_pr", _fake_fetch_bad)
    out2 = await pull_requests.get_pr_info("o/r", 1)
    assert out2["summary"] is None


@pytest.mark.asyncio
async def test_create_pull_request_normalizes_base_and_default_body(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    async def _fake_default_body(**_kwargs: Any) -> str:
        return "generated body"

    monkeypatch.setattr(pull_requests, "_build_default_pr_body", _fake_default_body)

    await pull_requests.create_pull_request(
        "o/r",
        title="My PR",
        head="refs/heads/feature",
        base="main",
        body=None,
        draft=True,
    )

    # Head should be normalized to branch-only.
    assert fake._github_request_calls[-1][3] == {
        "title": "My PR",
        "head": "feature",
        "base": "effective-main",
        "draft": True,
        "body": "generated body",
    }


@pytest.mark.asyncio
async def test_create_pull_request_structured_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()

    async def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("nope")

    fake._github_request = _boom  # type: ignore[assignment]
    _install_main(monkeypatch, pull_requests, fake)

    out = await pull_requests.create_pull_request(
        "o/r", title="t", head="h", base="main", body="b"
    )

    assert out["status"] == "error"
    assert out["context"] == "create_pull_request"
    assert out["path"] == "o/r h->main"


@pytest.mark.asyncio
async def test_recent_prs_for_branch_builds_head_filter_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    fake._queue_list_prs.extend(
        [
            {"json": [{"number": 1, "html_url": "u1"}, {"nope": True}, "x"]},
            {"json": [{"number": 2, "html_url": "u2"}, {"number": None}]},
        ]
    )

    out = await pull_requests.recent_prs_for_branch(
        "octo-org/octo-repo", branch="feature/test", include_closed=True
    )

    assert out["head_filter"] == "octo-org:feature/test"
    assert out["open"] == [{"number": 1, "html_url": "u1"}]
    assert out["closed"] == [{"number": 2, "html_url": "u2"}]

    # Qualified branch keeps explicit owner.
    fake._queue_list_prs[:] = [{"json": []}]
    out2 = await pull_requests.recent_prs_for_branch(
        "octo-org/octo-repo", branch="someone:refs/heads/feature/test"
    )
    assert out2["head_filter"] == "someone:feature/test"

    with pytest.raises(ValueError):
        await pull_requests.recent_prs_for_branch("bad", branch="x")
    with pytest.raises(ValueError):
        await pull_requests.recent_prs_for_branch("o/r", branch="")


@pytest.mark.asyncio
async def test_update_files_and_open_pr_happy_path(monkeypatch: pytest.MonkeyPatch):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    # Deterministic branch name.
    monkeypatch.setattr(pull_requests.os, "urandom", lambda n: b"\x00" * n)

    async def _fake_create_pr(**kwargs: Any):
        # Ensure base got normalized.
        assert kwargs["base"] == "effective-main"
        assert kwargs["head"] == "ally-00000000"
        return {"json": {"number": 123}}

    monkeypatch.setattr(pull_requests, "create_pull_request", _fake_create_pr)

    out = await pull_requests.update_files_and_open_pr(
        "o/r",
        title="Update",
        files=[
            {"path": "a.txt", "content": "hello"},
            {"path": "b.txt", "content_url": "https://example.com/b.txt"},
        ],
        base_branch="main",
        new_branch=None,
        body="body",
        draft=False,
    )

    assert out["branch"] == "ally-00000000"
    assert len(out["commits"]) == 2
    assert len(out["verifications"]) == 2

    # ensure_branch called with effective base.
    assert fake.ensure_branch_calls == [("o/r", "ally-00000000", "effective-main")]

    # Commits used correct bytes.
    assert fake.commit_calls[0]["body_bytes"] == b"hello"
    assert fake.commit_calls[1]["body_bytes"] == b"from-url"


@pytest.mark.asyncio
async def test_update_files_and_open_pr_validates_file_entries(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    out = await pull_requests.update_files_and_open_pr(
        "o/r", title="t", files=[], base_branch="main"
    )
    assert out["status"] == "error"
    assert out["context"] == "update_files_and_open_pr"

    out2 = await pull_requests.update_files_and_open_pr(
        "o/r", title="t", files=[{"content": "x"}], base_branch="main"
    )
    assert out2["status"] == "error"

    out3 = await pull_requests.update_files_and_open_pr(
        "o/r",
        title="t",
        files=[{"path": "a", "content": "x", "content_url": "u"}],
        base_branch="main",
    )
    assert out3["status"] == "error"


@pytest.mark.asyncio
async def test_update_files_and_open_pr_structured_error_on_load(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()

    async def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("load failed")

    fake._load_body_from_content_url = _boom  # type: ignore[assignment]
    _install_main(monkeypatch, pull_requests, fake)

    out = await pull_requests.update_files_and_open_pr(
        "o/r",
        title="t",
        files=[{"path": "a.txt", "content_url": "u"}],
        base_branch="main",
    )

    assert out["status"] == "error"
    assert out["context"] == "update_files_and_open_pr.load_content"
    assert out["path"] == "a.txt"


@pytest.mark.asyncio
async def test_get_pr_overview_happy_path_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
):
    from github_mcp.main_tools import pull_requests

    fake = FakeMain()
    _install_main(monkeypatch, pull_requests, fake)

    fake._queue_fetch_pr.append(
        {
            "json": {
                "number": 10,
                "title": "T",
                "state": "open",
                "draft": False,
                "merged": False,
                "html_url": "https://example/pr/10",
                "user": {"login": "octo", "html_url": "https://example/u"},
                "created_at": "2099-01-01T00:00:00Z",
                "head": {"sha": "abc", "ref": "feature"},
            }
        }
    )
    fake._queue_list_files.append(
        {
            "json": [
                {
                    "filename": "a",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                },
                "skip",
            ]
        }
    )
    fake._queue_status.append({"json": {"state": "failure"}})
    fake._queue_runs.append(
        {
            "json": {
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "feature",
                        "head_sha": "abc",
                        "html_url": "https://example/run/1",
                        "created_at": "2099-01-01T00:00:00Z",
                        "updated_at": "2099-01-01T00:01:00Z",
                    },
                    "skip",
                ]
            }
        }
    )

    out = await pull_requests.get_pr_overview("o/r", 10)

    assert out["pr"]["user"]["login"] == "octo"
    assert out["files"] == [
        {
            "filename": "a",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "changes": 1,
        }
    ]
    assert out["status_checks"]["state"] == "failure"
    assert out["workflow_runs"][0]["id"] == 1

    # If list_pr_changed_filenames explodes, files should be empty (defensive).
    async def _boom_list(*_args: Any, **_kwargs: Any):
        raise RuntimeError("nope")

    fake2 = FakeMain()
    _install_main(monkeypatch, pull_requests, fake2)
    fake2._queue_fetch_pr.append({"json": {"head": {"ref": "x"}}})
    fake2.list_pr_changed_filenames = _boom_list  # type: ignore[assignment]

    out2 = await pull_requests.get_pr_overview("o/r", 1)
    assert out2["files"] == []

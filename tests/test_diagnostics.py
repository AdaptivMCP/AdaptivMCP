from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from github_mcp.main_tools import diagnostics
import uuid as _stdlib_uuid


@dataclass
class _FakeMain:
    defaults_payload: dict[str, Any] = field(default_factory=dict)
    controller_repo: str = "controller/repo"
    controller_default_branch: str = "main"
    normalized_path: str = "normalized.txt"
    pr_response: dict[str, Any] = field(default_factory=dict)

    ensure_calls: list[dict[str, Any]] = field(default_factory=list)
    commit_calls: list[dict[str, Any]] = field(default_factory=list)
    pr_calls: list[dict[str, Any]] = field(default_factory=list)
    normalize_calls: list[str] = field(default_factory=list)

    # Match the interface used by diagnostics.pr_smoke_test
    @property
    def CONTROLLER_REPO(self) -> str:  # noqa: N802
        return self.controller_repo

    @property
    def CONTROLLER_DEFAULT_BRANCH(self) -> str:  # noqa: N802
        return self.controller_default_branch

    async def get_repo_defaults(self, *, full_name: str | None = None) -> dict[str, Any]:
        return {"defaults": dict(self.defaults_payload)}

    def _normalize_repo_path(self, path: str) -> str:
        self.normalize_calls.append(path)
        return self.normalized_path

    async def ensure_branch(self, *, full_name: str, branch: str, from_ref: str) -> dict[str, Any]:
        self.ensure_calls.append(
            {"full_name": full_name, "branch": branch, "from_ref": from_ref}
        )
        return {"ok": True}

    async def apply_text_update_and_commit(
        self,
        *,
        full_name: str,
        path: str,
        updated_content: str,
        branch: str,
        message: str,
    ) -> dict[str, Any]:
        self.commit_calls.append(
            {
                "full_name": full_name,
                "path": path,
                "updated_content": updated_content,
                "branch": branch,
                "message": message,
            }
        )
        return {"ok": True}

    async def create_pull_request(
        self,
        *,
        full_name: str,
        title: str,
        head: str,
        base: str,
        body: str,
        draft: bool,
    ) -> dict[str, Any]:
        self.pr_calls.append(
            {
                "full_name": full_name,
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            }
        )
        return dict(self.pr_response)


class _FakeUUID:
    def __init__(self, hex_value: str) -> None:
        self.hex = hex_value


@pytest.mark.anyio
async def test_pr_smoke_test_uses_repo_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMain(
        defaults_payload={"full_name": "o/r", "default_branch": "develop"},
        pr_response={"json": {"number": 42, "html_url": "https://example/pr/42"}},
        normalized_path="mcp_pr_smoke_test.txt",
    )

    # Deterministic branch name.
    monkeypatch.setattr(diagnostics, "_main", lambda: fake)
    monkeypatch.setattr(_stdlib_uuid, "uuid4", lambda: _FakeUUID("deadbeef" * 4))

    result = await diagnostics.pr_smoke_test(full_name=None, base_branch=None, draft=True)

    assert result["status"] == "ok"
    assert result["repository"] == "o/r"
    assert result["base"] == "develop"
    assert result["branch"] == "mcp-pr-smoke-deadbeef"
    assert result["pr_number"] == 42
    assert result["pr_url"] == "https://example/pr/42"

    assert fake.normalize_calls == ["mcp_pr_smoke_test.txt"]
    assert fake.ensure_calls == [
        {"full_name": "o/r", "branch": "mcp-pr-smoke-deadbeef", "from_ref": "develop"}
    ]
    assert fake.commit_calls and fake.commit_calls[0]["path"] == "mcp_pr_smoke_test.txt"
    assert fake.pr_calls and fake.pr_calls[0]["base"] == "develop"


@pytest.mark.anyio
async def test_pr_smoke_test_honors_explicit_full_name_and_base_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMain(
        defaults_payload={},
        controller_repo="controller/repo",
        controller_default_branch="main",
        pr_response={"json": {"number": 1, "html_url": "https://example/pr/1"}},
    )
    monkeypatch.setattr(diagnostics, "_main", lambda: fake)
    monkeypatch.setattr(_stdlib_uuid, "uuid4", lambda: _FakeUUID("01234567" * 4))

    result = await diagnostics.pr_smoke_test(
        full_name="explicit/repo",
        base_branch="release",
        draft=False,
    )

    assert result["status"] == "ok"
    assert result["repository"] == "explicit/repo"
    assert result["base"] == "release"
    assert result["branch"] == "mcp-pr-smoke-01234567"

    assert fake.ensure_calls[0]["from_ref"] == "release"
    assert fake.pr_calls[0]["draft"] is False


@pytest.mark.anyio
async def test_pr_smoke_test_error_when_pr_payload_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMain(
        defaults_payload={"full_name": "o/r", "default_branch": "main"},
        pr_response={"json": {}},
    )
    monkeypatch.setattr(diagnostics, "_main", lambda: fake)
    monkeypatch.setattr(_stdlib_uuid, "uuid4", lambda: _FakeUUID("aaaaaaaa" * 4))

    result = await diagnostics.pr_smoke_test(full_name=None, base_branch=None, draft=True)

    assert result["status"] == "error"
    assert result["ok"] is False
    assert result["repository"] == "o/r"
    assert result["base"] == "main"
    assert result["branch"] == "mcp-pr-smoke-aaaaaaaa"
    assert result["raw_response"] == {"json": {}}


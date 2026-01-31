from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import github_mcp.main_tools.files as files_mod


class FakeGitHubAPIError(Exception):
    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class FakeMain:
    # store[(full_name, branch, path)] -> {"text": str, "sha": str, "html_url": str}
    store: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    commits: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    sha_counter: int = 0

    GitHubAPIError = FakeGitHubAPIError

    def _next_sha(self) -> str:
        self.sha_counter += 1
        return f"sha{self.sha_counter}"  # deterministic for assertions

    async def _decode_github_content(
        self, full_name: str, path: str, branch: str
    ) -> dict[str, Any]:
        key = (full_name, branch, path)
        if key not in self.store:
            raise FakeGitHubAPIError("Not Found", status_code=404)
        payload = self.store[key]
        return {
            "text": payload["text"],
            "sha": payload["sha"],
            "html_url": payload.get("html_url"),
        }

    async def _perform_github_commit(
        self,
        *,
        full_name: str,
        path: str,
        message: str,
        body_bytes: bytes,
        branch: str,
        sha: str | None,
        ensure_parent: bool = True,
        **_kw: Any,
    ) -> dict[str, Any]:
        text = body_bytes.decode("utf-8")
        self.commits.append(
            {
                "full_name": full_name,
                "path": path,
                "message": message,
                "text": text,
                "sha": sha,
                "branch": branch,
                "ensure_parent": ensure_parent,
            }
        )
        new_sha = self._next_sha()
        self.store[(full_name, branch, path)] = {
            "text": text,
            "sha": new_sha,
            "html_url": f"https://example.test/{full_name}/blob/{branch}/{path}",
        }
        # Shape is intentionally loose; production code returns GitHub API response.
        return {"commit": {"sha": new_sha}, "content": {"sha": new_sha}}

    async def _resolve_file_sha(self, full_name: str, path: str, branch: str) -> str:
        key = (full_name, branch, path)
        if key not in self.store:
            raise FakeGitHubAPIError("Not Found", status_code=404)
        return self.store[key]["sha"]

    async def _github_request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.requests.append({"method": method, "endpoint": endpoint, **kwargs})

        if method != "DELETE":
            return {"ok": True}

        body = kwargs.get("json") or kwargs.get("data") or {}
        branch = body.get("branch", "main")

        # endpoint looks like: /repos/{full_name}/contents/{path}
        try:
            after_repos = endpoint.split("/repos/", 1)[1]
            full_name, after_full = after_repos.split("/contents/", 1)
            path = after_full.lstrip("/")
        except Exception:
            return {"ok": False, "reason": "unparseable endpoint"}

        self.store.pop((full_name, branch, path), None)
        return {"ok": True}


@pytest.fixture()
def fake_main(monkeypatch: pytest.MonkeyPatch) -> FakeMain:
    fake = FakeMain()

    # Reuse the same fake across calls.
    monkeypatch.setattr(files_mod, "_main", lambda: fake)

    # Keep normalization deterministic and independent of controller defaults.
    def _norm(full_name: str, branch: str, path: str) -> tuple[str, str]:
        _ = full_name
        b = (branch or "").strip() or "main"
        p = (path or "").strip().lstrip("/")
        return b, p

    monkeypatch.setattr(files_mod, "_normalize_write_context", _norm)
    return fake


@pytest.mark.anyio
async def test_create_file_success_and_diff(fake_main: FakeMain) -> None:
    res = await files_mod.create_file(
        "acme/repo",
        "docs/readme.md",
        "hello\n",
        branch="main",
        return_diff=True,
    )

    assert res["status"] == "created"
    assert res["verification"]["sha_before"] is None
    assert res["verification"]["sha_after"] == "sha1"
    assert "diff" in res
    assert res["diff"] is not None
    assert "+++" in res["diff"] and "---" in res["diff"]


@pytest.mark.anyio
async def test_create_file_existing_raises(fake_main: FakeMain) -> None:
    # Prepopulate as if it already exists.
    fake_main.store[("acme/repo", "main", "exists.txt")] = {
        "text": "x",
        "sha": "sha0",
        "html_url": "https://example.test/acme/repo/blob/main/exists.txt",
    }

    with pytest.raises(FakeGitHubAPIError) as exc:
        await files_mod.create_file("acme/repo", "exists.txt", "y")

    assert "already exists" in str(exc.value)


@pytest.mark.anyio
async def test_apply_text_update_and_commit_create_then_update(
    fake_main: FakeMain,
) -> None:
    created = await files_mod.apply_text_update_and_commit(
        "acme/repo",
        "new.txt",
        "v1\n",
        return_diff=True,
    )
    assert created["status"] == "committed"
    assert created["verification"]["sha_before"] is None
    assert created["verification"]["sha_after"] == "sha1"
    assert "+++" in (created.get("diff") or "")

    updated = await files_mod.apply_text_update_and_commit(
        "acme/repo",
        "new.txt",
        "v2\n",
        return_diff=True,
    )
    assert updated["status"] == "committed"
    assert updated["verification"]["sha_before"] == "sha1"
    assert updated["verification"]["sha_after"] == "sha2"
    diff = updated.get("diff") or ""
    assert "-v1" in diff and "+v2" in diff


@pytest.mark.anyio
async def test_move_file_moves_and_deletes(fake_main: FakeMain) -> None:
    # Seed source file.
    fake_main.store[("acme/repo", "main", "from.txt")] = {
        "text": "content\n",
        "sha": "sha0",
        "html_url": "https://example.test/acme/repo/blob/main/from.txt",
    }

    res = await files_mod.move_file("acme/repo", "from.txt", "to.txt")

    assert res["status"] == "moved"
    assert res["from_path"] == "from.txt"
    assert res["to_path"] == "to.txt"

    assert ("acme/repo", "main", "to.txt") in fake_main.store
    assert ("acme/repo", "main", "from.txt") not in fake_main.store


@pytest.mark.anyio
async def test_move_file_missing_delete_sha_is_noop(
    fake_main: FakeMain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_main.store[("acme/repo", "main", "from.txt")] = {
        "text": "content\n",
        "sha": "sha0",
        "html_url": "https://example.test/acme/repo/blob/main/from.txt",
    }

    async def _missing(full_name: str, path: str, branch: str) -> str:
        raise FakeGitHubAPIError("Not Found", status_code=404)

    monkeypatch.setattr(fake_main, "_resolve_file_sha", _missing)

    res = await files_mod.move_file("acme/repo", "from.txt", "to.txt")
    assert res["status"] == "moved"
    assert res["delete_result"]["status"] == "noop"

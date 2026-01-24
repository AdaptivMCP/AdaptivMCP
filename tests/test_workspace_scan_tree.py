from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _resolve_full_name(
        self, full_name: str | None, *, owner: str | None, repo: str | None
    ) -> str:
        return full_name or f"{owner}/{repo}"  # pragma: no cover

    def _resolve_ref(self, ref: str, *, branch: str | None) -> str:
        return branch or ref

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    def _workspace_deps(self) -> dict[str, Any]:
        async def clone_repo(
            _full_name: str, *, ref: str, preserve_changes: bool
        ) -> str:
            return self.repo_dir

        return {"clone_repo": clone_repo}


@pytest.mark.anyio
async def test_scan_workspace_tree_basic(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from github_mcp.workspace_tools import listing

    # Create a small repo-like tree.
    (tmp_path / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    (tmp_path / ".hidden").write_text("secret", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.txt").write_text("nope", encoding="utf-8")

    fake = _FakeTW(str(tmp_path))
    monkeypatch.setattr(listing, "_tw", lambda: fake)

    res = await listing.scan_workspace_tree(
        full_name="octo-org/octo-repo",
        ref="main",
        include_hidden=False,
        include_dirs=False,
        include_hash=True,
        include_line_count=True,
        include_head=True,
        head_max_lines=5,
        head_max_chars=100,
        max_entries=50,
        max_depth=10,
    )

    paths = [r["path"] for r in res["results"]]
    assert "a.txt" in paths
    assert "sub/c.txt" in paths
    assert "b.bin" in paths
    assert ".hidden" not in paths
    assert ".git/ignored.txt" not in paths

    a = next(r for r in res["results"] if r["path"] == "a.txt")
    assert a["is_binary"] is False
    assert a["line_count"] == 2
    assert a["sha256"] is not None
    assert a["head"]["lines"][0]["line"] == 1

    b = next(r for r in res["results"] if r["path"] == "b.bin")
    assert b["is_binary"] is True
    assert "line_count" not in b
    assert "head" not in b

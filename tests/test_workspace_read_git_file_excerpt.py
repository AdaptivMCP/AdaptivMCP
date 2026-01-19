from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    def _workspace_deps(self) -> dict[str, Any]:
        async def clone_repo(_full_name: str, *, ref: str, preserve_changes: bool) -> str:
            self.calls.append(
                {
                    "fn": "clone_repo",
                    "full_name": _full_name,
                    "ref": ref,
                    "preserve_changes": preserve_changes,
                }
            )
            return "/tmp/fake-repo"

        return {"clone_repo": clone_repo}


@pytest.mark.anyio
async def test_read_git_file_excerpt_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import fs

    fake = _FakeTW()
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    def _fake_git_show(*args: Any, **kwargs: Any) -> tuple[bool, list[dict[str, Any]], bool, str | None]:
        # Return 3 lines starting at 10.
        return (
            True,
            [
                {"line": 10, "text": "a"},
                {"line": 11, "text": "b"},
                {"line": 12, "text": "c"},
            ],
            False,
            None,
        )

    monkeypatch.setattr(fs, "_git_show_lines_excerpt_limited", _fake_git_show)

    res = await fs.read_git_file_excerpt(
        full_name="octo-org/octo-repo",
        ref="main",
        path="README.md",
        git_ref="HEAD~1",
        start_line=10,
        max_lines=50,
        max_chars=9999,
    )

    assert res["exists"] is True
    assert res["path"] == "README.md"
    assert res["git_ref"] == "HEAD~1"
    excerpt = res["excerpt"]
    assert excerpt["start_line"] == 10
    assert excerpt["end_line"] == 12
    assert [l["text"] for l in excerpt["lines"]] == ["a", "b", "c"]

    assert fake.calls and fake.calls[0]["fn"] == "clone_repo"


@pytest.mark.anyio
async def test_read_git_file_excerpt_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import fs

    fake = _FakeTW()
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    def _fake_git_show(*args: Any, **kwargs: Any) -> tuple[bool, list[dict[str, Any]], bool, str | None]:
        return (False, [], False, "no such path")

    monkeypatch.setattr(fs, "_git_show_lines_excerpt_limited", _fake_git_show)

    res = await fs.read_git_file_excerpt(
        full_name="octo-org/octo-repo",
        ref="main",
        path="MISSING.md",
        git_ref="HEAD",
        start_line=1,
        max_lines=20,
        max_chars=1000,
    )

    assert res["exists"] is False
    assert res["error"] == "no such path"


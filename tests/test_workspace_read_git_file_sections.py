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
async def test_read_git_file_sections_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import fs

    fake = _FakeTW()
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    def _fake_git_show(*args: Any, **kwargs: Any) -> tuple[bool, dict[str, Any], str | None]:
        return (
            True,
            {
                "start_line": 10,
                "end_line": 14,
                "parts": [
                    {
                        "part_index": 0,
                        "start_line": 10,
                        "end_line": 12,
                        "lines": [
                            {"line": 10, "text": "a"},
                            {"line": 11, "text": "b"},
                            {"line": 12, "text": "c"},
                        ],
                    },
                    {
                        "part_index": 1,
                        "start_line": 13,
                        "end_line": 14,
                        "lines": [
                            {"line": 13, "text": "d"},
                            {"line": 14, "text": "e"},
                        ],
                    },
                ],
                "truncated": False,
                "next_start_line": None,
                "max_sections": 5,
                "max_lines_per_section": 200,
                "max_chars_per_section": 80000,
                "overlap_lines": 20,
                "had_decoding_errors": False,
            },
            None,
        )

    monkeypatch.setattr(fs, "_git_show_lines_sections_limited", _fake_git_show)

    res = await fs.read_git_file_sections(
        full_name="octo-org/octo-repo",
        ref="main",
        path="README.md",
        git_ref="HEAD~1",
        start_line=10,
        max_sections=5,
        max_lines_per_section=200,
        max_chars_per_section=9999,
        overlap_lines=0,
    )

    assert res["exists"] is True
    assert res["path"] == "README.md"
    assert res["git_ref"] == "HEAD~1"
    sections = res["sections"]
    assert sections["start_line"] == 10
    assert sections["end_line"] == 14
    assert len(sections["parts"]) == 2
    assert fake.calls and fake.calls[0]["fn"] == "clone_repo"


@pytest.mark.anyio
async def test_read_git_file_sections_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import fs

    fake = _FakeTW()
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    def _fake_git_show(*args: Any, **kwargs: Any) -> tuple[bool, dict[str, Any], str | None]:
        return (
            False,
            {
                "start_line": 1,
                "end_line": 1,
                "parts": [],
                "truncated": False,
                "next_start_line": None,
                "max_sections": 5,
                "max_lines_per_section": 200,
                "max_chars_per_section": 80000,
                "overlap_lines": 20,
                "had_decoding_errors": False,
            },
            "no such path",
        )

    monkeypatch.setattr(fs, "_git_show_lines_sections_limited", _fake_git_show)

    res = await fs.read_git_file_sections(
        full_name="octo-org/octo-repo",
        ref="main",
        path="MISSING.md",
        git_ref="HEAD",
        start_line=1,
        max_sections=2,
        max_lines_per_section=50,
        max_chars_per_section=1000,
        overlap_lines=0,
    )

    assert res["exists"] is False
    assert res["error"] == "no such path"

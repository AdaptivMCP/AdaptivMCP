from __future__ import annotations

from pathlib import Path

import pytest


class _FakeTW:
    def __init__(self, repo_dir: str) -> None:
        self._repo_dir = repo_dir

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    def _workspace_deps(self):
        async def clone_repo(_full_name: str, *, ref: str, preserve_changes: bool) -> str:
            return self._repo_dir

        return {"clone_repo": clone_repo}


@pytest.mark.anyio
async def test_read_workspace_file_sections_chunks_with_line_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from github_mcp.workspace_tools import fs

    # Create a file with known lines.
    p = tmp_path / "demo.txt"
    p.write_text("\n".join([f"L{i}" for i in range(1, 21)]) + "\n", encoding="utf-8")

    fake = _FakeTW(str(tmp_path))
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    res = await fs.read_workspace_file_sections(
        full_name="octo-org/octo-repo",
        ref="main",
        path="demo.txt",
        start_line=5,
        max_sections=2,
        max_lines_per_section=5,
        max_chars_per_section=10_000,
        overlap_lines=1,
    )

    assert res["exists"] is True
    sections = res["sections"]
    assert sections["start_line"] == 5
    assert len(sections["parts"]) == 2
    assert sections["parts"][0]["start_line"] == 5
    assert sections["parts"][0]["end_line"] == 9
    # Second part should overlap by 1 line => starts at 9
    assert sections["parts"][1]["start_line"] == 9
    assert sections["parts"][1]["lines"][0]["line"] == 9


@pytest.mark.anyio
async def test_apply_workspace_operations_read_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from github_mcp.workspace_tools import fs

    p = tmp_path / "demo.txt"
    p.write_text("a\n" * 50, encoding="utf-8")

    fake = _FakeTW(str(tmp_path))
    monkeypatch.setattr(fs, "_tw", lambda: fake)

    res = await fs.apply_workspace_operations(
        full_name="octo-org/octo-repo",
        ref="main",
        operations=[
            {
                "op": "read_sections",
                "path": "demo.txt",
                "start_line": 1,
                "max_sections": 1,
                "max_lines_per_section": 10,
                "max_chars_per_section": 1000,
                "overlap_lines": 0,
            }
        ],
        preview_only=True,
    )

    assert isinstance(res, dict)
    assert "results" in res
    assert res["results"][0]["op"] == "read_sections"
    assert res["results"][0]["status"] == "ok"
    assert "parts" in res["results"][0]["sections"]

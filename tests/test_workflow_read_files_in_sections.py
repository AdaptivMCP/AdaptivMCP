from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    async def read_workspace_file_sections(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "read_workspace_file_sections", "kwargs": kwargs})
        path = kwargs.get("path")
        if path == "missing.txt":
            return {
                "full_name": kwargs.get("full_name"),
                "ref": kwargs.get("ref"),
                "path": path,
                "exists": False,
                "sections": {
                    "start_line": 1,
                    "end_line": 1,
                    "parts": [],
                    "truncated": False,
                },
            }
        return {
            "full_name": kwargs.get("full_name"),
            "ref": kwargs.get("ref"),
            "path": path,
            "exists": True,
            "sections": {
                "start_line": int(kwargs.get("start_line", 1) or 1),
                "end_line": 3,
                "parts": [
                    {
                        "part_index": 0,
                        "start_line": 1,
                        "end_line": 3,
                        "lines": [
                            {"line": 1, "text": "a"},
                            {"line": 2, "text": "b"},
                            {"line": 3, "text": "c"},
                        ],
                    }
                ],
                "truncated": False,
                "next_start_line": None,
            },
        }


@pytest.mark.anyio
async def test_workspace_read_files_in_sections_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_read_files_in_sections(
        full_name="octo-org/octo-repo",
        ref="main",
        paths=["a.txt", "missing.txt"],
        start_line=1,
        max_sections=2,
        max_lines_per_section=10,
        max_chars_per_section=1000,
        overlap_lines=0,
        include_missing=True,
    )

    assert res["ok"] is True
    assert res["status"] == "ok"
    assert len(res["files"]) == 2
    assert "missing.txt" in res["missing_paths"]
    assert sum(1 for c in fake.calls if c["fn"] == "read_workspace_file_sections") == 2

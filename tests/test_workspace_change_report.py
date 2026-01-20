from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    async def workspace_git_diff(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "workspace_git_diff", "kwargs": kwargs})
        return {
            "full_name": kwargs.get("full_name"),
            "ref": kwargs.get("ref"),
            "left_ref": kwargs.get("left_ref"),
            "right_ref": kwargs.get("right_ref"),
            "staged": False,
            "paths": None,
            "context_lines": kwargs.get("context_lines", 3),
            "diff": (
                "diff --git a/foo.txt b/foo.txt\n"
                "index 1111111..2222222 100644\n"
                "--- a/foo.txt\n"
                "+++ b/foo.txt\n"
                "@@ -10,2 +10,3 @@\n"
                " a\n"
                "-b\n"
                "+bb\n"
                "+c\n"
            ),
            "truncated": False,
            "numstat": [{"path": "foo.txt", "added": 2, "removed": 1, "is_binary": False}],
        }

    async def read_git_file_excerpt(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"fn": "read_git_file_excerpt", "kwargs": kwargs})
        return {
            "exists": True,
            "path": kwargs.get("path"),
            "git_ref": kwargs.get("git_ref"),
            "excerpt": {
                "start_line": kwargs.get("start_line"),
                "lines": [
                    {"line": kwargs.get("start_line", 1), "text": "x"},
                ],
                "truncated": False,
            },
        }


@pytest.mark.anyio
async def test_workspace_change_report_builds_hunks_and_excerpts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_change_report(
        full_name="octo-org/octo-repo",
        base_ref="main",
        head_ref="feature",
        max_files=10,
        max_hunks_per_file=5,
        include_diff=True,
        git_diff_args={"context_lines": 9},
        excerpt_args={"max_chars": 1234},
    )

    assert res["status"] == "ok"
    assert res["base_ref"] == "main"
    assert res["head_ref"] == "feature"
    assert "diff" in res and "@@" in res["diff"]
    assert res["numstat"][0]["path"] == "foo.txt"

    files = res["files"]
    assert len(files) == 1
    f0 = files[0]
    assert f0["path"] == "foo.txt"
    assert len(f0["hunks"]) == 1
    h0 = f0["hunks"][0]
    assert h0["old_start"] == 10
    assert h0["old_len"] == 2
    assert h0["new_start"] == 10
    assert h0["new_len"] == 3

    assert len(f0["excerpts"]) == 1
    ex = f0["excerpts"][0]
    assert ex["base"]["git_ref"] == "main"
    assert ex["head"]["git_ref"] == "feature"

    # Underlying tools were invoked.
    assert any(c["fn"] == "workspace_git_diff" for c in fake.calls)
    assert sum(1 for c in fake.calls if c["fn"] == "read_git_file_excerpt") == 2

    # Dynamic kwargs were passed through.
    diff_call = next(c for c in fake.calls if c["fn"] == "workspace_git_diff")
    assert diff_call["kwargs"].get("context_lines") == 9
    excerpt_calls = [c for c in fake.calls if c["fn"] == "read_git_file_excerpt"]
    assert excerpt_calls[0]["kwargs"].get("max_chars") == 1234
    assert excerpt_calls[1]["kwargs"].get("max_chars") == 1234


@pytest.mark.anyio
async def test_workspace_change_report_omits_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import workflows

    fake = _FakeTW()
    monkeypatch.setattr(workflows, "_tw", lambda: fake)

    res = await workflows.workspace_change_report(
        full_name="octo-org/octo-repo",
        base_ref="main",
        head_ref="feature",
        include_diff=False,
    )
    assert res["status"] == "ok"
    assert "diff" not in res

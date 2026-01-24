from __future__ import annotations

from typing import Any

import pytest


class _FakeTW:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._deps: dict[str, Any] = {}

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    def _workspace_deps(self) -> dict[str, Any]:
        async def clone_repo(
            _full_name: str, *, ref: str, preserve_changes: bool
        ) -> str:
            self.calls.append(
                {
                    "fn": "clone_repo",
                    "full_name": _full_name,
                    "ref": ref,
                    "preserve_changes": preserve_changes,
                }
            )
            return "/tmp/fake-repo"

        async def run_shell(
            cmd: str, *, cwd: str, timeout_seconds: float
        ) -> dict[str, Any]:
            self.calls.append({"fn": "run_shell", "cmd": cmd, "cwd": cwd})
            # First call is the diff, second is numstat.
            if "--numstat" in cmd:
                return {
                    "exit_code": 0,
                    "stdout": "3\t1\tfile_a.txt\n-\t-\timage.png\n",
                    "stderr": "",
                }
            return {
                "exit_code": 0,
                "stdout": "diff --git a/file_a.txt b/file_a.txt\n@@ -1 +1 @@\n-a\n+b\n",
                "stderr": "",
            }

        return {"clone_repo": clone_repo, "run_shell": run_shell}


@pytest.mark.anyio
async def test_workspace_git_diff_truncates_and_parses_numstat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import git_ops

    fake = _FakeTW()
    monkeypatch.setattr(git_ops, "_tw", lambda: fake)

    res = await git_ops.workspace_git_diff(
        full_name="octo-org/octo-repo",
        ref="main",
        left_ref="HEAD~1",
        right_ref="HEAD",
        context_lines=3,
        max_chars=10,
    )

    assert res["full_name"] == "octo-org/octo-repo"
    assert res["left_ref"] == "HEAD~1"
    assert res["right_ref"] == "HEAD"
    assert res["truncated"] is True
    assert isinstance(res["diff"], str) and len(res["diff"]) == 10

    numstat = res["numstat"]
    assert numstat[0]["path"] == "file_a.txt"
    assert numstat[0]["added"] == 3
    assert numstat[0]["removed"] == 1
    assert numstat[0]["is_binary"] is False
    assert numstat[1]["path"] == "image.png"
    assert numstat[1]["added"] is None
    assert numstat[1]["removed"] is None
    assert numstat[1]["is_binary"] is True

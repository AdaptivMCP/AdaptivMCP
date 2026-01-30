from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest

import github_mcp.workspace_tools.clone as clone_mod
import github_mcp.workspace_tools.stream_utils as stream_utils


def test_normalize_stream_text_crlf_and_cr() -> None:
    assert stream_utils.normalize_stream_text("a\r\nb\r\nc") == "a\nb\nc"


def test_text_stats_empty_and_lines() -> None:
    assert stream_utils.text_stats("") == (0, 0)
    assert stream_utils.text_stats("x") == (1, 1)
    assert stream_utils.text_stats("x\n") == (2, 2)
    assert stream_utils.text_stats("a\r\nb\r\nc") == (5, 3)


@dataclass
class _FakeDeps:
    called_with: list[dict[str, Any]]

    async def clone_repo(self, full_name: str, *, ref: str, preserve_changes: bool):
        self.called_with.append(
            {"full_name": full_name, "ref": ref, "preserve_changes": preserve_changes}
        )
        return f"/tmp/{full_name}/{ref}"


class _FakeTW:
    def __init__(self, deps: _FakeDeps, base_dir: str):
        self._deps = deps
        self._base_dir = base_dir

    def _resolve_full_name(self, full_name: str | None, *, owner: str | None, repo: str | None) -> str:
        if full_name:
            return full_name
        assert owner and repo
        return f"{owner}/{repo}"

    def _resolve_ref(self, ref: str, *, branch: str | None = None) -> str:
        return (branch or ref).strip()

    def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
        return ref

    def _workspace_path(self, full_name: str, ref: str) -> str:
        return os.path.join(self._base_dir, full_name.replace("/", "__"), ref)

    def _workspace_deps(self) -> dict[str, Any]:
        return {"clone_repo": self._deps.clone_repo}


@pytest.mark.anyio
async def test_ensure_workspace_clone_created_and_reset(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []
    deps = _FakeDeps(called_with=calls)
    tw = _FakeTW(deps, str(tmp_path))
    monkeypatch.setattr(clone_mod, "_tw", lambda: tw)

    # No .git directory yet => created True.
    res = await clone_mod.ensure_workspace_clone("o/r", ref="main", reset=False)
    assert res["created"] is True
    assert calls[-1]["preserve_changes"] is True

    # Create a fake .git folder in the workspace path; now created False.
    wdir = tw._workspace_path("o/r", "main")
    os.makedirs(os.path.join(wdir, ".git"), exist_ok=True)

    res2 = await clone_mod.ensure_workspace_clone("o/r", ref="main", reset=True)
    assert res2["created"] is False
    assert res2["reset"] is True
    assert calls[-1]["preserve_changes"] is False


@pytest.mark.anyio
async def test_ensure_workspace_clone_resolves_owner_repo(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[dict[str, Any]] = []
    deps = _FakeDeps(called_with=calls)
    tw = _FakeTW(deps, str(tmp_path))
    monkeypatch.setattr(clone_mod, "_tw", lambda: tw)

    res = await clone_mod.ensure_workspace_clone(None, owner="acme", repo="demo", branch="dev")
    assert res["ref"] == "dev"
    assert calls[-1]["full_name"] == "acme/demo"


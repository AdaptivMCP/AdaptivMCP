from __future__ import annotations

import asyncio

import pytest

from github_mcp import workspace
from github_mcp.workspace_leases import (
    workspace_identity_key,
    workspace_identity_path,
    workspace_lease,
)


def test_workspace_path_is_scoped_by_session_and_principal(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "github_mcp.workspace_leases._request_identity",
        lambda: ("user-a", "sess-1"),
    )
    monkeypatch.setattr(
        workspace,
        "_get_main_module",
        lambda: type("M", (), {"WORKSPACE_BASE_DIR": str(tmp_path)})(),
    )

    first = workspace._workspace_path("owner/repo", "main")
    assert "/.sessions/" in first
    assert first.endswith("/main")
    assert workspace_identity_key() in first

    monkeypatch.setattr(
        "github_mcp.workspace_leases._request_identity",
        lambda: ("user-b", "sess-2"),
    )
    second = workspace._workspace_path("owner/repo", "main")
    assert second != first


@pytest.mark.anyio
async def test_workspace_lease_serializes_same_workspace(tmp_path):
    workspace_dir = tmp_path / "repo"
    events: list[str] = []

    async def worker(name: str):
        async with workspace_lease(str(workspace_dir), timeout_seconds=2):
            events.append(f"{name}:enter")
            await asyncio.sleep(0.02)
            events.append(f"{name}:exit")

    await asyncio.gather(worker("a"), worker("b"))

    assert events in (
        ["a:enter", "a:exit", "b:enter", "b:exit"],
        ["b:enter", "b:exit", "a:enter", "a:exit"],
    )


@pytest.mark.anyio
async def test_workspace_lease_timeout_does_not_deadlock(tmp_path):
    workspace_dir = str(tmp_path / "repo")
    async with workspace_lease(workspace_dir):
        with pytest.raises(asyncio.TimeoutError):
            async with workspace_lease(workspace_dir, timeout_seconds=0.01):
                pass


def test_identity_path_does_not_include_raw_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "github_mcp.workspace_leases._request_identity",
        lambda: ("sensitive-user", "sensitive-session"),
    )
    path = workspace_identity_path(str(tmp_path), "owner/repo", "feature/x")
    assert "sensitive-user" not in path
    assert "sensitive-session" not in path
    assert "/.sessions/" in path

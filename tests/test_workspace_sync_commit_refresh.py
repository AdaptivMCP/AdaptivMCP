import asyncio
import types


def test_perform_github_commit_and_refresh_workspace_uses_main_overrides(monkeypatch):
    """When `main` (or `__main__`) exposes overrides, they should be used."""

    from github_mcp.main_tools import workspace_sync

    calls = {"commit": [], "ensure": []}

    async def fake_commit(**kwargs):
        calls["commit"].append(kwargs)
        return {"ok": True, "sha": "abc"}

    async def fake_ensure(**kwargs):
        calls["ensure"].append(kwargs)
        return {"ok": True}

    fake_main = types.SimpleNamespace(
        _perform_github_commit=fake_commit,
        ensure_workspace_clone=fake_ensure,
    )

    monkeypatch.setitem(workspace_sync.sys.modules, "main", fake_main)

    result = asyncio.run(
        workspace_sync._perform_github_commit_and_refresh_workspace(
            full_name="octo/example",
            path="README.md",
            message="msg",
            branch="feature",
            body_bytes=b"hi",
            sha=None,
        )
    )

    assert result == {"ok": True, "sha": "abc"}
    assert len(calls["commit"]) == 1
    assert calls["commit"][0]["branch"] == "feature"
    assert len(calls["ensure"]) == 1
    assert calls["ensure"][0] == {
        "full_name": "octo/example",
        "ref": "feature",
        "reset": True,
    }


def test_perform_github_commit_and_refresh_workspace_logs_refresh_error(monkeypatch, caplog):
    """Refresh errors should be logged but not fail the commit."""

    from github_mcp.main_tools import workspace_sync

    async def fake_commit(**kwargs):
        return {"ok": True}

    async def fake_ensure(**kwargs):
        return {"error": "boom"}

    fake_main = types.SimpleNamespace(
        _perform_github_commit=fake_commit,
        ensure_workspace_clone=fake_ensure,
    )
    monkeypatch.setitem(workspace_sync.sys.modules, "main", fake_main)

    with caplog.at_level("INFO"):
        result = asyncio.run(
            workspace_sync._perform_github_commit_and_refresh_workspace(
                full_name="octo/example",
                path="README.md",
                message="msg",
                branch="feature",
                body_bytes=b"hi",
                sha=None,
            )
        )

    assert result == {"ok": True}
    assert any(
        "Repo mirror refresh returned an error after commit" in r.message for r in caplog.records
    )


def test_perform_github_commit_and_refresh_workspace_swallow_refresh_exception(monkeypatch, caplog):
    """Exceptions during refresh should be logged and swallowed."""

    from github_mcp.main_tools import workspace_sync

    async def fake_commit(**kwargs):
        return {"ok": True}

    async def fake_ensure(**kwargs):
        raise RuntimeError("nope")

    fake_main = types.SimpleNamespace(
        _perform_github_commit=fake_commit,
        ensure_workspace_clone=fake_ensure,
    )
    monkeypatch.setitem(workspace_sync.sys.modules, "main", fake_main)

    with caplog.at_level("INFO"):
        result = asyncio.run(
            workspace_sync._perform_github_commit_and_refresh_workspace(
                full_name="octo/example",
                path="README.md",
                message="msg",
                branch="feature",
                body_bytes=b"hi",
                sha=None,
            )
        )

    assert result == {"ok": True}
    assert any(
        "Failed to refresh repo mirror after commit" in r.message for r in caplog.records
    )


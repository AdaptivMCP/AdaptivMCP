from __future__ import annotations

from types import ModuleType

import pytest


class _AsyncNullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Resp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, *, get_map: dict[str, _Resp], post_map: dict[str, _Resp]):
        self.get_map = get_map
        self.post_map = post_map
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str):
        self.calls.append(("GET", path))
        return self.get_map.get(path, _Resp(500, text="missing stub"))

    async def post(self, path: str, json=None):
        self.calls.append(("POST", path))
        return self.post_map.get(path, _Resp(500, text="missing stub"))


class _GitHubAPIError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_main_fallback_imports_server_when_main_unavailable(monkeypatch):
    import github_mcp.main_tools._main as main_mod

    calls: list[str] = []
    server_module = ModuleType("github_mcp.server")
    tools_main_module = ModuleType("github_mcp.tools_main")
    tools_ws_module = ModuleType("github_mcp.tools_workspace")

    def _fake_import(name: str):
        calls.append(name)
        if name == "main":
            raise ImportError("boom")
        if name == "github_mcp.tools_workspace":
            return tools_ws_module
        if name == "github_mcp.tools_main":
            return tools_main_module
        if name == "github_mcp.server":
            return server_module
        raise ImportError(f"unexpected import {name}")

    monkeypatch.setattr(main_mod.importlib, "import_module", _fake_import)

    returned = main_mod._main()
    assert returned is server_module
    # Ensure the fallback path attempted to register tools.
    assert "github_mcp.tools_workspace" in calls
    assert "github_mcp.tools_main" in calls


@pytest.mark.asyncio
async def test_create_branch_happy_path(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(
        get_map={
            "/repos/o/r/git/ref/heads/main": _Resp(
                200,
                payload={"object": {"sha": "base-sha"}},
            )
        },
        post_map={
            "/repos/o/r/git/refs": _Resp(
                201,
                payload={"ref": "refs/heads/feature", "object": {"sha": "base-sha"}},
            )
        },
    )

    dummy_main = ModuleType("main")
    dummy_main._effective_ref_for_repo = lambda _full, ref: ref
    dummy_main._github_client_instance = lambda: client
    dummy_main._get_concurrency_semaphore = lambda: _AsyncNullCtx()
    dummy_main.GitHubAPIError = _GitHubAPIError

    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    out = await branches.create_branch("o/r", "feature", from_ref="main")
    assert out["status_code"] == 201
    assert out["json"]["ref"] == "refs/heads/feature"
    assert ("GET", "/repos/o/r/git/ref/heads/main") in client.calls
    assert ("POST", "/repos/o/r/git/refs") in client.calls


@pytest.mark.asyncio
async def test_ensure_branch_creates_when_missing(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(
        get_map={
            "/repos/o/r/git/ref/heads/feature": _Resp(404, payload={}),
            "/repos/o/r/git/ref/heads/main": _Resp(200, payload={"object": {"sha": "s"}}),
        },
        post_map={
            "/repos/o/r/git/refs": _Resp(201, payload={"ref": "refs/heads/feature"}),
        },
    )

    dummy_main = ModuleType("main")
    dummy_main._effective_ref_for_repo = lambda _full, ref: ref
    dummy_main._github_client_instance = lambda: client
    dummy_main._get_concurrency_semaphore = lambda: _AsyncNullCtx()
    dummy_main.GitHubAPIError = _GitHubAPIError

    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    out = await branches.ensure_branch("o/r", "feature", from_ref="main")
    assert out["status_code"] == 201
    assert out["json"]["ref"] == "refs/heads/feature"


@pytest.mark.asyncio
async def test_create_branch_raises_on_unexpected_base_ref_status(monkeypatch):
    from github_mcp.main_tools import branches

    client = _DummyClient(
        get_map={
            "/repos/o/r/git/ref/heads/main": _Resp(500, payload={}, text="nope"),
        },
        post_map={},
    )

    dummy_main = ModuleType("main")
    dummy_main._effective_ref_for_repo = lambda _full, ref: ref
    dummy_main._github_client_instance = lambda: client
    dummy_main._get_concurrency_semaphore = lambda: _AsyncNullCtx()
    dummy_main.GitHubAPIError = _GitHubAPIError

    monkeypatch.setattr(branches, "_main", lambda: dummy_main)

    with pytest.raises(_GitHubAPIError):
        await branches.create_branch("o/r", "feature", from_ref="main")


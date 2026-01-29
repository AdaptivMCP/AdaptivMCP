import asyncio


def test_workspace_batch_missing_ref_fail_fast(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    # Avoid touching remote check.
    monkeypatch.setattr(batch, "_remote_branch_exists", lambda *a, **k: True)

    out = asyncio.run(
        batch.workspace_batch(
            full_name="o/r",
            plans=[{"stage": {}}, {"ref": "ok", "stage": {}}],
            fail_fast=True,
        )
    )

    assert out["ok"] is False
    assert out["status"] == "partial"
    assert out["plans"][0]["status"] == "error"
    assert "plan.ref" in out["plans"][0]["error"]
    assert len(out["plans"]) == 1


def test_workspace_batch_missing_ref_continue_when_not_fail_fast(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            if cmd.startswith("git add"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            if cmd.startswith("git diff --cached"):
                return {"exit_code": 0, "stdout": "x\n", "stderr": ""}
            return {"exit_code": 0, "stdout": "", "stderr": ""}

    deps = DummyDeps()

    class DummyTW:
        def _workspace_deps(self):
            return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())

    out = asyncio.run(
        batch.workspace_batch(
            full_name="o/r",
            plans=[{"stage": {}}, {"ref": "ok", "stage": {}}],
            fail_fast=False,
        )
    )

    assert out["ok"] is False
    assert len(out["plans"]) == 2
    assert out["plans"][0]["status"] == "error"
    assert out["plans"][1]["ok"] is True
    assert out["plans"][1]["steps"]["stage"]["staged_files"] == ["x"]


def test_workspace_batch_shorthand_ops_maps_to_apply_ops(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    seen = {}

    async def fake_apply_workspace_operations(**kwargs):
        seen.update(kwargs)
        return {"status": "ok", "ok": True}

    class DummyTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())
    monkeypatch.setattr(batch, "apply_workspace_operations", fake_apply_workspace_operations)

    out = asyncio.run(
        batch.workspace_batch(
            full_name="o/r",
            plans=[{"ref": "b", "operations": [{"op": "write", "path": "a", "content": "c"}]}],
        )
    )

    assert out["ok"] is True
    assert seen["ref"] == "b"
    assert isinstance(seen["operations"], list) and seen["operations"][0]["op"] == "write"
    assert seen["preview_only"] is False


def test_workspace_batch_create_branch_if_missing_calls_create(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    calls = {}

    async def fake_remote_exists(*_a, **_k):
        return False

    async def fake_create_branch(**kwargs):
        calls.update(kwargs)
        return {"status": "ok", "ok": True}

    class DummyTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())
    monkeypatch.setattr(batch, "_remote_branch_exists", fake_remote_exists)
    monkeypatch.setattr(batch, "workspace_create_branch", fake_create_branch)

    out = asyncio.run(
        batch.workspace_batch(
            full_name="o/r",
            plans=[
                {
                    "ref": "new-branch",
                    "create_branch_if_missing": True,
                    "create_branch_args": {"push": False, "foo": "bar"},
                }
            ],
        )
    )

    assert out["ok"] is True
    assert out["plans"][0]["steps"]["branch_exists"]["exists"] is False
    assert out["plans"][0]["steps"]["create_branch"]["ok"] is True
    assert calls["full_name"] == "o/r"
    assert calls["base_ref"] == "main"
    assert calls["new_branch"] == "new-branch"
    # create_branch_args can override push behavior.
    assert calls["push"] is False
    assert calls["foo"] == "bar"


def test_workspace_batch_commit_uses_files_variant_when_files_present(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    seen = {"files": 0, "all": 0}

    async def fake_commit_workspace_files(**kwargs):
        seen["files"] += 1
        return {"status": "ok", "ok": True, "commit_sha": "abc"}

    async def fake_commit_workspace(**kwargs):
        seen["all"] += 1
        return {"status": "ok", "ok": True, "commit_sha": "def"}

    class DummyTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())
    monkeypatch.setattr(batch, "commit_workspace_files", fake_commit_workspace_files)
    monkeypatch.setattr(batch, "commit_workspace", fake_commit_workspace)

    out = asyncio.run(
        batch.workspace_batch(
            full_name="o/r",
            plans=[
                {
                    "ref": "b",
                    "commit": {"message": "m", "files": ["a.txt"], "push": False},
                },
                {
                    "ref": "c",
                    "commit": {"message": "m2", "add_all": False, "push": False},
                },
            ],
            fail_fast=False,
        )
    )

    assert out["plans"][0]["steps"]["commit"]["commit_sha"] == "abc"
    assert out["plans"][1]["steps"]["commit"]["commit_sha"] == "def"
    assert seen["files"] == 1
    assert seen["all"] == 1

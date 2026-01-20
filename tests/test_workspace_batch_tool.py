import asyncio


def test_workspace_batch_module_imports():
    # Import should not raise.
    import github_mcp.workspace_tools.batch as _batch  # noqa: F401


class DummyDeps:
    def __init__(self):
        self.calls = []

    async def clone_repo(self, full_name: str, ref: str, preserve_changes: bool = True):
        self.calls.append(("clone_repo", full_name, ref, preserve_changes))
        return "/tmp/repo"

    async def run_shell(self, cmd: str, cwd: str, timeout_seconds: float = 0):
        self.calls.append(("run_shell", cmd, cwd, timeout_seconds))
        if cmd.startswith("git ls-remote"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git add"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git reset"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git diff --cached --name-only"):
            return {"exit_code": 0, "stdout": "file.txt\n", "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}


def test_workspace_batch_stage_only(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    deps = DummyDeps()

    class DummyTW:
        def _workspace_deps(self):
            return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())

    result = asyncio.run(
        batch.workspace_batch(
            full_name="octo/example",
            plans=[{"ref": "feature", "stage": {}}],
        )
    )

    assert result["ok"] is True
    assert result["plans"][0]["steps"]["stage"]["staged_files"] == ["file.txt"]


def test_workspace_batch_passes_dynamic_step_kwargs(monkeypatch):
    import github_mcp.workspace_tools.batch as batch

    called = {}

    async def fake_apply_workspace_operations(**kwargs):
        called["apply_ops"] = kwargs
        return {"status": "ok", "ok": True}

    async def fake_run_tests(**kwargs):
        called["tests"] = kwargs
        return {"status": "success"}

    class DummyTW:
        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(batch, "_tw", lambda: DummyTW())
    monkeypatch.setattr(batch, "apply_workspace_operations", fake_apply_workspace_operations)
    monkeypatch.setattr(batch, "run_tests", fake_run_tests)

    result = asyncio.run(
        batch.workspace_batch(
            full_name="octo/example",
            plans=[
                {
                    "ref": "feature",
                    "apply_ops": {"operations": [{"op": "write", "path": "a", "content": "b"}], "fail_fast": False, "preview_only": True},
                    "tests": {"test_command": "pytest -q", "use_temp_venv": False},
                }
            ],
        )
    )

    assert result["ok"] is True
    assert called["apply_ops"]["fail_fast"] is False
    assert called["apply_ops"]["preview_only"] is True
    assert called["tests"]["test_command"] == "pytest -q"
    assert called["tests"]["use_temp_venv"] is False

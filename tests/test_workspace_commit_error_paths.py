import asyncio


def _mk_dummy_tw(*, run_shell_impl):
    import github_mcp.workspace_tools.commit as commit

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            return await run_shell_impl(cmd, cwd=cwd, timeout_seconds=timeout_seconds)

    deps = DummyDeps()

    class DummyTW:
        def _workspace_deps(self):
            return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

        def _resolve_full_name(self, full_name, *, owner=None, repo=None):
            return full_name

        def _resolve_ref(self, ref, *, branch=None):
            return ref

        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    return commit, DummyTW


def test_commit_workspace_errors_when_no_changes(monkeypatch):
    async def run_shell_impl(cmd: str, *, cwd: str, timeout_seconds: float = 0):
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "stdout": "\n", "stderr": ""}
        if cmd == "git add -A":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"unexpected cmd: {cmd}")

    commit, DummyTW = _mk_dummy_tw(run_shell_impl=run_shell_impl)
    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(commit.commit_workspace(full_name="o/r"))
    assert out.get("ok") is False
    assert "No changes to commit" in str(out.get("error") or out)


def test_commit_workspace_surfaces_git_add_failure(monkeypatch):
    async def run_shell_impl(cmd: str, *, cwd: str, timeout_seconds: float = 0):
        if cmd == "git add -A":
            return {"exit_code": 1, "stdout": "", "stderr": "nope"}
        raise AssertionError(f"unexpected cmd: {cmd}")

    commit, DummyTW = _mk_dummy_tw(run_shell_impl=run_shell_impl)
    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(commit.commit_workspace(full_name="o/r"))
    assert out.get("ok") is False
    assert "git add failed" in str(out.get("error") or out)


def test_commit_workspace_surfaces_git_commit_failure(monkeypatch):
    async def run_shell_impl(cmd: str, *, cwd: str, timeout_seconds: float = 0):
        if cmd == "git add -A":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "stdout": " M a.txt\n", "stderr": ""}
        if cmd.startswith("git commit -m"):
            return {"exit_code": 1, "stdout": "", "stderr": "commit fail"}
        raise AssertionError(f"unexpected cmd: {cmd}")

    commit, DummyTW = _mk_dummy_tw(run_shell_impl=run_shell_impl)
    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(commit.commit_workspace(full_name="o/r", push=False))
    assert out.get("ok") is False
    assert "git commit failed" in str(out.get("error") or out)


def test_commit_workspace_surfaces_git_push_failure(monkeypatch):
    async def run_shell_impl(cmd: str, *, cwd: str, timeout_seconds: float = 0):
        if cmd == "git add -A":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "stdout": " M a.txt\n", "stderr": ""}
        if cmd.startswith("git commit -m"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd.startswith("git push origin"):
            return {"exit_code": 1, "stdout": "", "stderr": "push fail"}
        raise AssertionError(f"unexpected cmd: {cmd}")

    commit, DummyTW = _mk_dummy_tw(run_shell_impl=run_shell_impl)
    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(commit.commit_workspace(full_name="o/r", push=True))
    assert out.get("ok") is False
    assert "git push failed" in str(out.get("error") or out)


def test_commit_workspace_files_surfaces_no_staged_changes(monkeypatch):
    async def run_shell_impl(cmd: str, *, cwd: str, timeout_seconds: float = 0):
        if cmd.startswith("git add --"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if cmd == "git diff --cached --name-only":
            return {"exit_code": 0, "stdout": "\n", "stderr": ""}
        raise AssertionError(f"unexpected cmd: {cmd}")

    commit, DummyTW = _mk_dummy_tw(run_shell_impl=run_shell_impl)
    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(
        commit.commit_workspace_files(full_name="o/r", files=["a.txt"], push=False)
    )
    assert out.get("ok") is False
    assert "No staged changes" in str(out.get("error") or out)

import asyncio


def test_commit_module_imports():
    import github_mcp.workspace_tools.commit as _commit  # noqa: F401


def test_slim_shell_result_strips_and_handles_non_dict():
    from github_mcp.workspace_tools import commit

    slim = commit._slim_shell_result(
        {"exit_code": 0, "stdout": " ok \n", "stderr": "  \n"}
    )
    assert slim == {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": ""}

    assert commit._slim_shell_result("nope")["raw"] == "nope"


def test_get_workspace_changes_summary_parses_and_filters_prefix(monkeypatch):
    import github_mcp.workspace_tools.commit as commit

    status_out = "\n".join(
        [
            " M modified.txt",
            "A  added.txt",
            "D  deleted.txt",
            "R  old.txt -> new.txt",
            "?? untracked.txt",
            " M sub/only.txt",
        ]
    )

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            assert cwd == "/tmp/repo"
            if cmd.startswith("git status"):
                return {"exit_code": 0, "stdout": status_out, "stderr": ""}
            raise AssertionError(f"unexpected cmd: {cmd}")

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

    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    all_out = asyncio.run(
        commit.get_workspace_changes_summary(full_name="o/r", ref="main")
    )
    assert all_out["has_changes"] is True
    assert all_out["summary"] == {
        "modified": 2,
        "added": 1,
        "deleted": 1,
        "renamed": 1,
        "untracked": 1,
    }

    pref = asyncio.run(
        commit.get_workspace_changes_summary(
            full_name="o/r", ref="main", path_prefix="sub"
        )
    )
    assert pref["summary"]["modified"] == 1
    assert pref["changes"] == [
        {"status": "M", "path": "sub/only.txt", "src": "sub/only.txt", "dst": None}
    ]


def test_commit_workspace_files_requires_non_empty_file_list():
    import github_mcp.workspace_tools.commit as commit

    # commit_workspace_files is wrapped by @mcp_tool, so validation errors are
    # surfaced as a structured error response rather than raising.
    out = asyncio.run(commit.commit_workspace_files(full_name="o/r", files=[]))
    assert out.get("ok") is False
    assert "files must be a non-empty list" in str(out.get("error") or out)


def test_get_workspace_changes_summary_enforces_max_files(monkeypatch):
    import github_mcp.workspace_tools.commit as commit

    status_out = "\n".join([" M a.txt", " M b.txt", "?? c.txt"])

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            if cmd.startswith("git status"):
                return {"exit_code": 0, "stdout": status_out, "stderr": ""}
            raise AssertionError(f"unexpected cmd: {cmd}")

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

    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(
        commit.get_workspace_changes_summary(full_name="o/r", ref="main", max_files=2)
    )
    assert out["has_changes"] is True
    assert out["max_files"] == 2
    assert out["changes_truncated"] is True
    assert len(out["changes"]) == 2


def test_get_workspace_changes_summary_status_exit_code_returns_error(monkeypatch):
    import github_mcp.workspace_tools.commit as commit

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            if cmd.startswith("git status"):
                return {"exit_code": 1, "stdout": "", "stderr": "boom"}
            raise AssertionError(f"unexpected cmd: {cmd}")

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

    monkeypatch.setattr(commit, "_tw", lambda: DummyTW())

    out = asyncio.run(commit.get_workspace_changes_summary(full_name="o/r", ref="main"))
    assert out.get("ok") is False
    assert "git status failed" in str(out.get("error") or out)

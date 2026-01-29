import asyncio
import os
import tempfile


def test_git_worktree_helpers_parse_and_clip():
    import github_mcp.workspace_tools.git_worktree as gw

    assert gw._clip_text("abc", max_chars=10) == ("abc", False)
    assert gw._clip_text("abcdef", max_chars=3) == ("abc", True)
    assert gw._clip_text("abcdef", max_chars=4) == ("abc…", True)

    rows = gw._parse_tabbed_rows(["a\tb\tc\td\te"], expected_cols=4)
    assert rows == [["a", "b", "c", "d\te"]]

    parsed = gw._parse_porcelain_v1(
        [
            "## main...origin/main [ahead 1]",
            "M  staged.txt",
            " M unstaged.txt",
            "?? new.txt",
        ]
    )
    assert parsed["branch"].startswith("##")
    assert parsed["staged"] == ["staged.txt"]
    assert parsed["unstaged"] == ["unstaged.txt"]
    assert parsed["untracked"] == ["new.txt"]
    assert parsed["is_clean"] is False


def test_workspace_git_log_clips_and_parses(monkeypatch):
    import github_mcp.workspace_tools.git_worktree as gw

    calls = []

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
            calls.append(cmd)
            if cmd.startswith("git checkout"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            if "git log" in cmd:
                # Two entries; make it long so clipping triggers.
                stdout = (
                    """aaaaaaaa\tauthor\t2020-01-01T00:00:00+00:00\t""" + "x" * 200 + "\n"
                    "bbbbbbbb\tauthor\t2020-01-02T00:00:00+00:00\tsecond\n"
                )
                return {"exit_code": 0, "stdout": stdout, "stderr": ""}
            raise AssertionError(cmd)

    deps = DummyDeps()

    class DummyTW:
        def _workspace_deps(self):
            return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(gw, "_tw", lambda: DummyTW())

    out = asyncio.run(
        gw.workspace_git_log(full_name="o/r", ref="main", max_entries=2, max_chars=80)
    )

    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["commits"]) >= 1
    assert calls[0].startswith("git checkout")


def test_workspace_git_checkout_rekeys_workspace(monkeypatch):
    import github_mcp.workspace_tools.git_worktree as gw

    with tempfile.TemporaryDirectory() as td:
        old_dir = os.path.join(td, "old")
        os.makedirs(old_dir, exist_ok=True)

        def fake_workspace_path(full_name: str, ref: str) -> str:
            return os.path.join(td, f"{full_name.replace('/', '_')}_{ref}")

        calls = []

        class DummyDeps:
            async def clone_repo(self, full_name: str, ref: str, preserve_changes: bool = True):
                calls.append(("clone_repo", ref, preserve_changes))
                if preserve_changes:
                    return old_dir
                recreated = os.path.join(td, "recreated_old")
                os.makedirs(recreated, exist_ok=True)
                return recreated

            async def run_shell(self, cmd: str, *, cwd: str, timeout_seconds: float = 0):
                calls.append(("run_shell", cmd, cwd))
                return {"exit_code": 0, "stdout": "", "stderr": ""}

        deps = DummyDeps()

        class DummyTW:
            def _workspace_deps(self):
                return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

            def _effective_ref_for_repo(self, full_name: str, ref: str):
                return ref

        monkeypatch.setattr(gw, "_tw", lambda: DummyTW())
        monkeypatch.setattr(gw, "_workspace_path", fake_workspace_path)

        out = asyncio.run(
            gw.workspace_git_checkout(
                full_name="o/r",
                ref="main",
                target="feature",
                create=False,
                push=False,
                rekey_workspace=True,
            )
        )

        assert out["ok"] is True
        assert out["moved_workspace"] is True
        assert out["repo_dir"].endswith("o_r_feature")
        assert os.path.exists(out["repo_dir"]) is True
        assert out["refreshed_old_repo_dir"] is not None


def test_workspace_git_checkout_rejects_invalid_target(monkeypatch):
    import github_mcp.workspace_tools.git_worktree as gw

    class DummyDeps:
        async def clone_repo(self, *_a, **_k):
            return "/tmp/repo"

        async def run_shell(self, *_a, **_k):
            raise AssertionError("run_shell should not be called for invalid target")

    deps = DummyDeps()

    class DummyTW:
        def _workspace_deps(self):
            return {"clone_repo": deps.clone_repo, "run_shell": deps.run_shell}

        def _effective_ref_for_repo(self, full_name: str, ref: str):
            return ref

    monkeypatch.setattr(gw, "_tw", lambda: DummyTW())

    out = asyncio.run(
        gw.workspace_git_checkout(full_name="o/r", ref="main", target="bad..ref")
    )
    assert out.get("ok") is False
    assert "invalid" in str(out.get("error") or out)

import asyncio
import io
import json
import subprocess

from github_mcp.workspace_tools import rg as workspace_rg


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_rg_list_workspace_files_falls_back_to_python(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("a", encoding="utf-8")
    (repo_dir / "b.txt").write_text("b", encoding="utf-8")
    (repo_dir / ".hidden.txt").write_text("h", encoding="utf-8")
    (repo_dir / "sub").mkdir()
    (repo_dir / "sub" / "c.py").write_text("print('c')", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    result = asyncio.run(
        workspace_rg.rg_list_workspace_files(
            full_name="octo/example",
            ref="main",
            path="",
            include_hidden=False,
            glob=["*.txt", "*.py"],
            exclude_paths=["sub"],
            max_results=10,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "python"
    assert ".hidden.txt" not in result["files"]
    assert "a.txt" in result["files"]
    assert "sub/c.py" not in result["files"]


def test_rg_tools_default_excludes_skip_venv_mcp_even_when_hidden_enabled(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("a", encoding="utf-8")
    (repo_dir / ".venv-mcp").mkdir()
    (repo_dir / ".venv-mcp" / "venv.txt").write_text("venv", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    # include_hidden=True would normally include .venv-mcp, but we now apply a
    # default exclude for it when callers don't supply exclude_* filters.
    result = asyncio.run(
        workspace_rg.rg_list_workspace_files(
            full_name="octo/example",
            ref="main",
            include_hidden=True,
            glob=["*.txt"],
            max_results=50,
        )
    )

    assert result.get("error") is None
    assert "a.txt" in result["files"]
    assert ".venv-mcp/venv.txt" not in result["files"]


def test_rg_search_workspace_returns_line_numbers_and_context(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("one\nfoo\nthree\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    result = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="foo",
            path="",
            regex=False,
            case_sensitive=True,
            include_paths=["a.txt"],
            max_results=10,
            context_lines=1,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "python"
    assert result["matches"]
    m = result["matches"][0]
    assert m["path"] == "a.txt"
    assert m["line"] == 2
    assert m["text"] == "foo"
    assert "excerpt" in m
    ex = m["excerpt"]
    assert ex["start_line"] == 1
    assert ex["end_line"] == 3
    assert [ln["line"] for ln in ex["lines"]] == [1, 2, 3]


def test_rg_search_workspace_falls_back_when_rg_popen_fails(tmp_path, monkeypatch):
    """If rg is present but fails to start, we should degrade to Python."""

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("one\nfoo\nthree\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: True)

    def _boom(*args, **kwargs):
        raise OSError("rg failed to exec")

    monkeypatch.setattr(workspace_rg.subprocess, "Popen", _boom)

    result = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="foo",
            path="",
            regex=False,
            case_sensitive=True,
            max_results=10,
            context_lines=0,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "python"
    assert result["matches"]
    assert result["matches"][0]["text"] == "foo"


def test_rg_search_workspace_default_excludes_can_be_overridden(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("foo\n", encoding="utf-8")
    (repo_dir / ".venv-mcp").mkdir()
    (repo_dir / ".venv-mcp" / "venv.txt").write_text("foo\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    # Default behavior (include_hidden=True): .venv-mcp is still excluded.
    result = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="foo",
            include_hidden=True,
            max_results=50,
        )
    )
    assert result.get("error") is None
    assert {m["path"] for m in result["matches"]} == {"a.txt"}

    # Explicit exclude_paths (even empty) disables default injection.
    result2 = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="foo",
            include_hidden=True,
            exclude_paths=[],
            max_results=50,
        )
    )
    assert result2.get("error") is None
    assert {m["path"] for m in result2["matches"]} == {"a.txt", ".venv-mcp/venv.txt"}


def test_rg_list_workspace_files_include_paths_do_not_duplicate_base_rel(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "subdir").mkdir()
    (repo_dir / "subdir" / "target.txt").write_text("ok", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: True)

    class DummyCompleted:
        def __init__(self):
            self.returncode = 0
            self.stdout = "subdir/target.txt\n"
            self.stderr = ""

    monkeypatch.setattr(
        workspace_rg.subprocess, "run", lambda *args, **kwargs: DummyCompleted()
    )

    result = asyncio.run(
        workspace_rg.rg_list_workspace_files(
            full_name="octo/example",
            ref="main",
            path="subdir",
            include_paths=["subdir/target.txt"],
            max_results=10,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "rg"
    assert result["files"] == ["subdir/target.txt"]


def test_rg_search_workspace_include_paths_do_not_duplicate_base_rel(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "subdir").mkdir()
    (repo_dir / "subdir" / "target.txt").write_text("ok\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: True)

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            payload = {
                "type": "match",
                "data": {
                    "path": {"text": "subdir/target.txt"},
                    "line_number": 1,
                    "submatches": [{"start": 0}],
                    "lines": {"text": "ok\n"},
                },
            }
            self.stdout = io.StringIO(json.dumps(payload) + "\n")
            self.stderr = io.StringIO("")
            self.returncode = 0

        def poll(self):
            return self.returncode

        def kill(self):
            return None

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(workspace_rg.subprocess, "Popen", DummyPopen)

    result = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="ok",
            path="subdir",
            include_paths=["subdir/target.txt"],
            max_results=10,
            context_lines=0,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "rg"
    assert result["matches"][0]["path"] == "subdir/target.txt"


def test_safe_communicate_kills_on_timeout(monkeypatch):
    """Regression: ensure a stuck child process can't hang subsequent tool calls."""

    calls = {"communicate": 0, "killed": False}

    class DummyProc:
        def communicate(self, timeout=None):
            calls["communicate"] += 1
            if calls["communicate"] == 1:
                raise subprocess.TimeoutExpired(cmd=["rg"], timeout=timeout or 0)
            return "out", "err"

        def kill(self):
            calls["killed"] = True

    out, err = workspace_rg._safe_communicate(DummyProc(), timeout=0.001)
    assert calls["killed"] is True
    assert calls["communicate"] >= 2
    assert out == "out"
    assert err == "err"

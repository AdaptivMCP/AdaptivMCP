import os
import pytest


@pytest.mark.asyncio
async def test_workspace_self_heal_branch_heals_mangled_branch(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    full_name = "owner/repo"
    branch = "feature/bad"

    def ws_path(_full_name: str, ref: str) -> str:
        # mimic github_mcp.workspace._workspace_path shape (ref munged)
        return str(tmp_path / ref.replace("/", "__"))

    monkeypatch.setattr(tw, "_workspace_path", ws_path)
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda _full_name, ref: ref)
    monkeypatch.setattr(tw, "_default_branch_for_repo", lambda _full_name: "main")
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    # deterministic new branch name
    class _FakeUUID:
        hex = "deadbeef" * 4

    monkeypatch.setattr(tw.uuid, "uuid4", lambda: _FakeUUID())

    # Prepare workspace dirs
    bad_dir = ws_path(full_name, branch)
    main_dir = ws_path(full_name, "main")
    new_branch = f"heal/{branch}-deadbeef"
    new_dir = ws_path(full_name, new_branch)

    os.makedirs(bad_dir, exist_ok=True)
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(new_dir, exist_ok=True)

    # track calls
    calls = []

    async def fake_clone_repo(_full_name, ref=None, preserve_changes=False):
        if ref == branch:
            return bad_dir
        if ref == "main":
            return main_dir
        if ref == new_branch:
            return new_dir
        # allow other refs by mapping to main
        return main_dir

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append((cmd, cwd))
        # Simulate mangled state: wrong branch checked out.
        if cmd == "git branch --show-current":
            return {"exit_code": 0, "timed_out": False, "stdout": "other\n", "stderr": ""}
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "timed_out": False, "stdout": " M file.txt\n", "stderr": ""}
        if cmd == "git diff --name-only --diff-filter=U":
            return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": ""}
        if cmd == "git log -n 1 --oneline":
            return {"exit_code": 0, "timed_out": False, "stdout": "abc123 test\n", "stderr": ""}
        # default ok
        return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": ""}

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "run_shell": fake_run_shell,
            "ensure_write_allowed": lambda *a, **k: None,
        },
    )

    # Create a marker file so we can confirm the directory is removed.
    with open(os.path.join(bad_dir, "marker.txt"), "w", encoding="utf-8") as f:
        f.write("x")

    res = await tw.workspace_self_heal_branch(full_name=full_name, branch=branch)

    assert res["healed"] is True
    assert res["mangled"] is True
    assert res["new_branch"] == new_branch
    assert res["repo_dir"] == new_dir

    # local workspace dir for mangled branch should be removed
    assert not os.path.exists(bad_dir)

    # branch deletion + new branch creation should have invoked git push commands
    cmds = "\n".join(c for c, _ in calls)
    assert "git push origin --delete feature/bad" in cmds
    assert f"git push -u origin {new_branch}" in cmds


@pytest.mark.asyncio
async def test_workspace_self_heal_branch_noop_when_healthy(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    full_name = "owner/repo"
    branch = "feature/good"

    def ws_path(_full_name: str, ref: str) -> str:
        return str(tmp_path / ref.replace("/", "__"))

    monkeypatch.setattr(tw, "_workspace_path", ws_path)
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda _full_name, ref: ref)
    monkeypatch.setattr(tw, "_default_branch_for_repo", lambda _full_name: "main")
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    good_dir = ws_path(full_name, branch)
    os.makedirs(good_dir, exist_ok=True)

    async def fake_clone_repo(_full_name, ref=None, preserve_changes=False):
        return good_dir

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        if cmd == "git branch --show-current":
            return {"exit_code": 0, "timed_out": False, "stdout": f"{branch}\n", "stderr": ""}
        if cmd == "git status --porcelain":
            return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": ""}
        if cmd == "git diff --name-only --diff-filter=U":
            return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": ""}
        return {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": ""}

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "run_shell": fake_run_shell,
        },
    )

    res = await tw.workspace_self_heal_branch(full_name=full_name, branch=branch)
    assert res["healed"] is False
    assert res["mangled"] is False
    assert any(s["action"] == "No action" for s in res["steps"])

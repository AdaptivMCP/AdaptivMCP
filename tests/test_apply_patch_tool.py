import asyncio

from github_mcp.workspace_tools import fs as workspace_fs


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir
        self.applied: list[str] = []
        self.fail_with: Exception | None = None

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        async def apply_patch_to_repo(repo_dir, patch):
            if self.fail_with is not None:
                raise self.fail_with
            self.applied.append(patch)

        async def run_shell(cmd, cwd):
            # Should not be invoked in these tests.
            raise AssertionError(f"run_shell should not be called: {cmd}")

        return {
            "clone_repo": clone_repo,
            "apply_patch_to_repo": apply_patch_to_repo,
            "run_shell": run_shell,
        }

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_apply_patch_reports_diff_stats_and_includes_log_diff(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    diff_text = """diff --git a/a.txt b/a.txt
index 0000000..1111111 100644
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
"""

    result = asyncio.run(
        workspace_fs.apply_patch(
            full_name="octo/example",
            ref="main",
            patch=diff_text,
        )
    )

    assert result.get("error") is None
    assert result["ok"] is True
    assert result["patches_applied"] == 1

    # Client-facing responses should include __log_* fields so the model and
    # user see the same payload used to render tool log visuals.
    assert result.get("__log_diff")

    # But derived, safe metadata should be present.
    assert result.get("diff_stats") == {"added": 1, "removed": 1}

    assert dummy.applied == [diff_text]


def test_apply_patch_structured_error_includes_safe_debug_args(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    dummy.fail_with = ValueError("bad patch")
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    diff_text = """diff --git a/a.txt b/a.txt
index 0000000..1111111 100644
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
"""

    result = asyncio.run(
        workspace_fs.apply_patch(
            full_name="octo/example",
            ref="main",
            patch=diff_text,
        )
    )

    assert result.get("status") == "error"
    detail = result.get("error_detail") or {}
    assert detail.get("category") == "validation"

    debug = (detail.get("debug") or {}).get("args") or {}

    # These are safe, low-entropy digests; patch text itself should not be included.
    assert debug.get("patches") == 1
    assert isinstance(debug.get("patch_digests"), list)
    assert len(debug["patch_digests"]) == 1

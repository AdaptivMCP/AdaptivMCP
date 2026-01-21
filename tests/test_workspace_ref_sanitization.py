import os
import sys
from pathlib import Path


def test_sanitize_workspace_ref_strips_separators_and_drives():
    from github_mcp import workspace

    assert workspace._sanitize_workspace_ref("/tmp") == "tmp"
    assert workspace._sanitize_workspace_ref("feature/test") == "feature__test"


def test_sanitize_workspace_ref_does_not_truncate_or_hash():
    from github_mcp import workspace

    long_ref = "a" * 200
    sanitized = workspace._sanitize_workspace_ref(long_ref)

    assert sanitized == long_ref


def test_sanitize_workspace_ref_preserves_symbols():
    from github_mcp import workspace

    ref = "feature-1.2.3+topic@branch name"
    assert workspace._sanitize_workspace_ref(ref) == ref


def test_workspace_path_never_creates_nested_dirs(tmp_path: Path, monkeypatch):
    from github_mcp import workspace

    # Force a deterministic workspace base dir for the test.
    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    monkeypatch.setattr(main_mod, "WORKSPACE_BASE_DIR", str(tmp_path), raising=False)

    workspace_dir = workspace._workspace_path("octo-org/octo-repo", "feature/test")

    rel = os.path.relpath(workspace_dir, str(tmp_path))
    parts = rel.split(os.sep)
    assert parts == ["octo-org__octo-repo", "feature__test"]

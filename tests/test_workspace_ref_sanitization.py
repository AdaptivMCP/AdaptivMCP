from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def test_sanitize_workspace_ref_strips_separators_and_drives():
    from github_mcp import workspace

    assert workspace._sanitize_workspace_ref("/tmp") == "tmp"
    assert workspace._sanitize_workspace_ref("feature/test") == "feature_test"
    assert workspace._sanitize_workspace_ref("C:\\temp\\x") == "C_temp_x"


def test_sanitize_workspace_ref_truncates_and_adds_stable_hash():
    from github_mcp import workspace

    long_ref = "a" * 200
    sanitized = workspace._sanitize_workspace_ref(long_ref)

    assert len(sanitized) <= 80
    # Should keep a short digest suffix for collision resistance.
    assert sanitized.count("-") == 1
    assert len(sanitized.split("-")[-1]) == 12


def test_workspace_path_never_creates_nested_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from github_mcp import workspace

    # Force a deterministic workspace base dir for the test.
    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    monkeypatch.setattr(main_mod, "WORKSPACE_BASE_DIR", str(tmp_path), raising=False)

    workspace_dir = workspace._workspace_path("octo-org/octo-repo", "feature/test")

    rel = os.path.relpath(workspace_dir, str(tmp_path))
    parts = rel.split(os.sep)
    assert parts == ["octo-org__octo-repo", "feature_test"]


def test_workspace_path_blocks_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from github_mcp import workspace

    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    monkeypatch.setattr(main_mod, "WORKSPACE_BASE_DIR", str(tmp_path), raising=False)

    workspace_dir = Path(workspace._workspace_path("octo-org/octo-repo", "../../etc/passwd"))

    # The resulting path must remain within the base directory.
    assert Path(os.path.commonpath([str(workspace_dir), str(tmp_path)])) == tmp_path
    # And it must be exactly two levels under base_dir (repo_key/ref)
    assert workspace_dir.relative_to(tmp_path).parts[0] == "octo-org__octo-repo"
    assert len(workspace_dir.relative_to(tmp_path).parts) == 2

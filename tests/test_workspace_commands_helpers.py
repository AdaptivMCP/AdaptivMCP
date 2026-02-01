from __future__ import annotations

from pathlib import Path

from github_mcp.workspace_tools import commands


def test_normalize_command_payload_prefers_command_lines() -> None:
    requested, lines = commands._normalize_command_payload(
        "echo ignored",
        ["echo one\necho two", "echo three"],
    )

    assert requested == "echo one\necho two\necho three"
    assert lines == ["echo one", "echo two", "echo three"]


def test_normalize_command_payload_handles_string_input() -> None:
    requested, lines = commands._normalize_command_payload(
        123,
        None,
    )

    assert requested == "123"
    assert lines == ["123"]


def test_looks_like_pytest_command_checks_lines() -> None:
    assert commands._looks_like_pytest_command(
        command="echo nope",
        command_lines=["pytest -q"],
    )

    assert not commands._looks_like_pytest_command(
        command="python -m pip",
        command_lines=None,
    )


def test_augment_env_for_pytest_sets_defaults() -> None:
    env = {"PYTEST_ADDOPTS": "-k smoke"}
    updated = commands._augment_env_for_pytest(env)

    assert updated["PYTHONDONTWRITEBYTECODE"] == "1"
    assert updated["PYTEST_ADDOPTS"] == "-k smoke -p no:cacheprovider"


def test_resolve_workdir_permits_relative_and_absolute(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subdir = repo_dir / "sub"
    subdir.mkdir()
    (repo_dir / "file.txt").write_text("hi", encoding="utf-8")

    assert commands._resolve_workdir(str(repo_dir), "sub") == str(subdir.resolve())
    assert commands._resolve_workdir(str(repo_dir), "file.txt") == str(
        repo_dir.resolve()
    )

    parent_dir = repo_dir.parent
    assert commands._resolve_workdir(str(repo_dir), "..") == str(parent_dir.resolve())

    abs_path = str(subdir.resolve())
    assert commands._resolve_workdir(str(repo_dir), abs_path) == abs_path


def test_safe_repo_relative_path_handles_invalid_values(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    assert (
        commands._safe_repo_relative_path(str(repo_dir), " ") == ".mcp_tmp/invalid_path"
    )

    abs_path = str((repo_dir / "abs").resolve())
    assert commands._safe_repo_relative_path(str(repo_dir), abs_path) == abs_path


def test_cleanup_test_artifacts_removes_known_paths(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    pytest_cache = repo_dir / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "data.txt").write_text("cache", encoding="utf-8")

    pycache_dir = repo_dir / "pkg" / "__pycache__"
    pycache_dir.mkdir(parents=True)
    (pycache_dir / "mod.cpython-311.pyc").write_bytes(b"\x00\x01")

    coverage_file = repo_dir / ".coverage"
    coverage_file.write_text("coverage", encoding="utf-8")

    summary = commands._cleanup_test_artifacts(str(repo_dir))

    assert summary["error_count"] == 0
    assert not pytest_cache.exists()
    assert not pycache_dir.exists()
    assert not coverage_file.exists()

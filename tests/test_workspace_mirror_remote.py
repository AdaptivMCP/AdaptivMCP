from __future__ import annotations

import asyncio
from typing import Any


def test_ensure_repo_remote_updates_mismatch(tmp_path) -> None:
    from github_mcp import workspace

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    calls: list[str] = []

    async def run_shell(
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append(command)
        if command == "git remote get-url origin":
            return {
                "exit_code": 0,
                "stdout": "https://github.com/octo-org/other-repo.git\n",
                "stderr": "",
            }
        if command.startswith("git remote set-url origin"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    asyncio.run(
        workspace._ensure_repo_remote(
            run_shell,
            str(repo_dir),
            "octo-org/octo-repo",
            timeout_seconds=0,
        )
    )

    assert calls[0] == "git remote get-url origin"
    assert calls[1].startswith("git remote set-url origin")


def test_ensure_repo_remote_adds_origin_when_missing(tmp_path) -> None:
    from github_mcp import workspace

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    calls: list[str] = []

    async def run_shell(
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 0,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append(command)
        if command == "git remote get-url origin":
            return {"exit_code": 2, "stdout": "", "stderr": "No such remote"}
        if command.startswith("git remote add origin"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    asyncio.run(
        workspace._ensure_repo_remote(
            run_shell,
            str(repo_dir),
            "octo-org/octo-repo",
            timeout_seconds=0,
        )
    )

    assert calls[0] == "git remote get-url origin"
    assert calls[1].startswith("git remote add origin")

import asyncio

import pytest

from github_mcp import workspace


def test_run_git_with_retry_retries_rate_limit(monkeypatch):
    calls: list[str] = []

    async def fake_run_shell(cmd: str, *, cwd, timeout_seconds, env=None):
        calls.append(cmd)
        if len(calls) < 3:
            return {"exit_code": 1, "stderr": "secondary rate limit"}
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", 0.1)
    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(workspace, "_jitter_sleep_seconds", lambda delay: 0.0)
    monkeypatch.setattr(workspace.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        workspace._run_git_with_retry(
            fake_run_shell, "git fetch", cwd=None, timeout_seconds=1, env=None
        )
    )

    assert result["exit_code"] == 0
    assert calls == ["git fetch", "git fetch", "git fetch"]
    assert sleep_calls == [0.0, 0.0]


def test_run_git_with_retry_no_retry_when_disabled(monkeypatch):
    async def fake_run_shell(cmd: str, *, cwd, timeout_seconds, env=None):
        return {"exit_code": 1, "stderr": "rate limit"}

    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 0)

    result = asyncio.run(
        workspace._run_git_with_retry(
            fake_run_shell, "git fetch", cwd=None, timeout_seconds=1, env=None
        )
    )

    assert result["exit_code"] == 1

import asyncio

import pytest

from github_mcp import workspace


@pytest.mark.parametrize(
    "message,expected",
    [
        ("fatal: rate limit exceeded", True),
        ("Secondary rate limit is hit", True),
        ("ABUSE DETECTION mechanism triggered", True),
        ("authentication failed", False),
        ("", False),
        (None, False),
    ],
)
def test_is_git_rate_limit_error(message, expected):
    assert workspace._is_git_rate_limit_error(message) is expected


@pytest.mark.asyncio
async def test_run_git_with_retry_retries_on_rate_limit(monkeypatch):
    calls = {"n": 0}

    async def fake_run_shell(cmd, cwd, timeout_seconds, env=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"exit_code": 128, "stderr": "fatal: secondary rate limit"}
        return {"exit_code": 0, "stdout": "ok"}

    # Make retries deterministic and fast.
    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", 1)
    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", 10)
    monkeypatch.setattr(workspace, "_jitter_sleep_seconds", lambda delay: 0)

    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await workspace._run_git_with_retry(
        fake_run_shell,
        "git fetch",
        cwd="/tmp",
        timeout_seconds=5,
        env=None,
    )

    assert result["exit_code"] == 0
    assert calls["n"] == 2
    assert slept == [0]


@pytest.mark.asyncio
async def test_run_git_with_retry_does_not_retry_non_rate_limit(monkeypatch):
    calls = {"n": 0}

    async def fake_run_shell(cmd, cwd, timeout_seconds, env=None):
        calls["n"] += 1
        return {"exit_code": 1, "stderr": "fatal: authentication failed"}

    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 10)

    result = await workspace._run_git_with_retry(
        fake_run_shell,
        "git fetch",
        cwd="/tmp",
        timeout_seconds=5,
        env=None,
    )

    assert result["exit_code"] == 1
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_run_git_with_retry_respects_max_attempts(monkeypatch):
    calls = {"n": 0}

    async def fake_run_shell(cmd, cwd, timeout_seconds, env=None):
        calls["n"] += 1
        return {"exit_code": 128, "stderr": "rate limit"}

    monkeypatch.setattr(workspace.config, "GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 0)

    result = await workspace._run_git_with_retry(
        fake_run_shell,
        "git fetch",
        cwd="/tmp",
        timeout_seconds=5,
        env=None,
    )

    assert result["exit_code"] == 128
    assert calls["n"] == 1

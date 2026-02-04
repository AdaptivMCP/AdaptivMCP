import asyncio
import uuid

import pytest


def test_async_dedupe_failure_is_not_cached():
    """If the shared work raises, the next call should recompute (no negative cache)."""

    from github_mcp.mcp_server import decorators

    key = f"dedupe-failure-{uuid.uuid4()}"
    counter = {"calls": 0}

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> int:
            async def _boom() -> str:
                counter["calls"] += 1
                raise RuntimeError("boom")

            with pytest.raises(RuntimeError):
                await decorators._maybe_dedupe_call(key, _boom, ttl_s=60.0)

            async def _ok() -> str:
                counter["calls"] += 1
                return "ok"

            result = await decorators._maybe_dedupe_call(key, _ok, ttl_s=60.0)
            assert result == "ok"
            return counter["calls"]

        calls = loop.run_until_complete(_scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert calls == 2


def test_run_shell_double_cancel_still_terminates_process_group(monkeypatch):
    """Cancelling again during cleanup should still terminate the subprocess group."""

    from github_mcp import workspace

    if workspace.os.name == "nt":
        # POSIX-only process group logic.
        return

    started = asyncio.Event()
    allow_wait_return = asyncio.Event()

    class _FakeProc:
        pid = 4545
        returncode = None

        async def communicate(self):
            started.set()
            # Never returns unless cancelled by wait_for; we want CancelledError path.
            await asyncio.Event().wait()

        async def wait(self):
            # Block until the test allows completion.
            await allow_wait_return.wait()
            return 0

        def kill(self):
            return None

    async def _fake_create_subprocess_shell(*_args, **_kwargs):
        return _FakeProc()

    killpg_calls: list[tuple[int, int]] = []

    def _fake_killpg(pid: int, sig: int):
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(
        workspace.asyncio, "create_subprocess_shell", _fake_create_subprocess_shell
    )
    monkeypatch.setattr(workspace.os, "killpg", _fake_killpg)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> None:
            task = asyncio.create_task(workspace._run_shell("sleep 999", timeout_seconds=0))
            await started.wait()

            # First cancellation triggers the CancelledError handler.
            task.cancel()

            # Yield so the task enters its cancellation handler, then cancel again.
            await asyncio.sleep(0)
            task.cancel()

            # Allow proc.wait() to complete so cleanup can finish.
            allow_wait_return.set()

            with pytest.raises(asyncio.CancelledError):
                await task

        loop.run_until_complete(_scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert killpg_calls, "Expected process group termination even with repeated cancellation"
    assert killpg_calls[0][0] == 4545

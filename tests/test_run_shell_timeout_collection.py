import asyncio

from github_mcp import workspace


def test_run_shell_timeout_collect_output_is_bounded(monkeypatch):
    """Regression: ADAPTIV_MCP_TIMEOUT_COLLECT_SECONDS=0 must not hang."""

    class FakeProc:
        pid = 123
        returncode = 124

        def __init__(self):
            self._calls = 0

        async def communicate(self):
            self._calls += 1
            if self._calls == 1:
                # This coroutine will never be awaited (we force wait_for timeout).
                await asyncio.Event().wait()
            # Simulate a hung communicate on output collection.
            await asyncio.Event().wait()

        async def wait(self):
            return 0

        def kill(self):
            return None

    async def fake_create_subprocess_shell(*args, **kwargs):
        return FakeProc()

    async def fake_wait_for(coro, timeout):
        # The initial command wait_for should time out.
        if timeout == 1:
            # This is the bounded output-collection path.
            try:
                coro.close()
            except Exception:
                pass
            raise asyncio.TimeoutError()
        if timeout == 0.01:
            try:
                coro.close()
            except Exception:
                pass
            raise asyncio.TimeoutError()
        return await coro

    monkeypatch.setattr(
        workspace.asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )
    monkeypatch.setattr(workspace.asyncio, "wait_for", fake_wait_for)

    async def run():
        return await workspace._run_shell("echo hi", timeout_seconds=0.01)

    result = asyncio.run(asyncio.wait_for(run(), timeout=0.1))

    assert result["timed_out"] is True
    assert "Failed to collect process output after timeout" in (
        result.get("stderr") or ""
    )

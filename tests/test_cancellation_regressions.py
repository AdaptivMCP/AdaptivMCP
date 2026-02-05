import asyncio
import uuid

from github_mcp.mcp_server import decorators


def test_async_dedupe_cancellation_does_not_cancel_shared_work():
    """Regression: caller cancellation must not abort shared deduped work.

    Hosted MCP deployments can see upstream disconnects mid-workflow. In that
    situation, the server should:
    - propagate asyncio.CancelledError to the *caller*,
    - but keep the shared in-flight work running,
    - so a subsequent retry with the same dedupe key can reuse the result.
    """

    key = f"dedupe-cancel-{uuid.uuid4()}"
    counter = {"calls": 0}

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> tuple[str, int]:
            started = asyncio.Event()
            proceed = asyncio.Event()

            async def _work_cancelled() -> str:
                counter["calls"] += 1
                started.set()
                # Block until the test allows completion. This avoids long
                # sleeps while still ensuring the work is in-flight.
                await proceed.wait()
                return "unreachable"

            task = asyncio.create_task(
                decorators._maybe_dedupe_call(key, _work_cancelled, ttl_s=60.0)
            )
            await started.wait()

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Allow the shared work to finish.
            proceed.set()

            async def _work_ok() -> str:
                counter["calls"] += 1
                return "ok"

            result = await decorators._maybe_dedupe_call(key, _work_ok, ttl_s=60.0)
            return result, counter["calls"]

        result, calls = loop.run_until_complete(_scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    # The retry should reuse the original in-flight work (and not execute _work_ok).
    assert result == "unreachable"
    assert calls == 1


def test_mcp_tool_cancellation_propagates():
    """Regression: cancellations must not be converted into structured errors."""

    tool_name = f"cancel_tool_{uuid.uuid4().hex}"

    blocker = asyncio.Event()

    @decorators.mcp_tool(name=tool_name, write_action=False)
    async def _tool() -> str:
        started.set()
        await blocker.wait()
        return "unreachable"

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> None:
            task = asyncio.create_task(_tool())
            await started.wait()
            task.cancel()
            await task

        started = asyncio.Event()
        try:
            loop.run_until_complete(_scenario())
        except asyncio.CancelledError:
            # Expected: cancellation is propagated.
            pass
        else:
            raise AssertionError("Expected asyncio.CancelledError to be raised")
    finally:
        loop.close()
        asyncio.set_event_loop(None)

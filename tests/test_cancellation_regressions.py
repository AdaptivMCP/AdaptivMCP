import asyncio
import uuid

from github_mcp.mcp_server import decorators


def test_async_dedupe_cancellation_is_not_cached():
    """Regression: Cancelled work must not poison the async dedupe cache.

    Expected behavior:
    - A cancelled call raises asyncio.CancelledError.
    - The dedupe cache entry is removed.
    - A subsequent call with the same key executes normally.
    """

    key = f"dedupe-cancel-{uuid.uuid4()}"
    counter = {"calls": 0}

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _scenario() -> tuple[str, int]:
            started = asyncio.Event()

            async def _work_cancelled() -> str:
                counter["calls"] += 1
                started.set()
                # Ensure we are cancellable while awaiting.
                await asyncio.sleep(60)
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

            async def _work_ok() -> str:
                counter["calls"] += 1
                return "ok"

            result = await decorators._maybe_dedupe_call(key, _work_ok, ttl_s=60.0)
            return result, counter["calls"]

        result, calls = loop.run_until_complete(_scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert result == "ok"
    assert calls == 2


def test_mcp_tool_cancellation_propagates():
    """Regression: cancellations must not be converted into structured errors."""

    tool_name = f"cancel_tool_{uuid.uuid4().hex}"

    @decorators.mcp_tool(name=tool_name, write_action=False)
    async def _tool() -> str:
        started.set()
        await asyncio.sleep(60)
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

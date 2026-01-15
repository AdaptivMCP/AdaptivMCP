from __future__ import annotations

import asyncio

import pytest

from github_mcp.async_utils import active_event_loop, refresh_async_client


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.is_closed = False
        self.closed_calls = 0

    async def aclose(self) -> None:
        self.is_closed = True
        self.closed_calls += 1


@pytest.mark.anyio
async def test_active_event_loop_returns_running_loop() -> None:
    loop = asyncio.get_running_loop()
    assert active_event_loop() is loop


def test_refresh_async_client_returns_existing_when_loop_matches() -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        client = _FakeAsyncClient()

        refreshed, refreshed_loop = refresh_async_client(
            client,
            client_loop=loop,
            rebuild=_FakeAsyncClient,
            force_refresh=False,
        )

        assert refreshed is client
        assert refreshed_loop is loop
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_refresh_async_client_force_refresh_rebuilds() -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        client = _FakeAsyncClient()

        refreshed, refreshed_loop = refresh_async_client(
            client,
            client_loop=loop,
            rebuild=_FakeAsyncClient,
            force_refresh=True,
        )

        assert refreshed is not client
        assert refreshed_loop is loop

        # A forced refresh schedules best-effort shutdown of the prior client on
        # the provided loop. Drain tasks to avoid "coroutine was never awaited"
        # warnings when the loop is closed.
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending))
    finally:
        asyncio.set_event_loop(None)
        loop.close()

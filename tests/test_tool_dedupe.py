import asyncio
import uuid

import pytest

from github_mcp.mcp_server import decorators


@pytest.mark.asyncio
async def test_async_dedupe_caches_result_within_loop():
    key = f"dedupe-{uuid.uuid4()}"
    counter = {"calls": 0}

    async def _work():
        counter["calls"] += 1
        return "ok"

    result1 = await decorators._maybe_dedupe_call(key, _work)
    result2 = await decorators._maybe_dedupe_call(key, _work)

    assert result1 == "ok"
    assert result2 == "ok"
    assert counter["calls"] == 1


def test_async_dedupe_is_scoped_per_event_loop():
    key = f"dedupe-{uuid.uuid4()}"
    counter = {"calls": 0}

    async def _work():
        counter["calls"] += 1
        return "ok"

    loop1 = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop1)
        loop1.run_until_complete(decorators._maybe_dedupe_call(key, _work))
    finally:
        loop1.close()

    loop2 = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop2)
        loop2.run_until_complete(decorators._maybe_dedupe_call(key, _work))
    finally:
        loop2.close()

    asyncio.set_event_loop(None)

    assert counter["calls"] == 2


def test_sync_dedupe_caches_result():
    key = f"dedupe-{uuid.uuid4()}"
    counter = {"calls": 0}

    def _work():
        counter["calls"] += 1
        return "ok"

    result1 = decorators._maybe_dedupe_call_sync(key, _work)
    result2 = decorators._maybe_dedupe_call_sync(key, _work)

    assert result1 == "ok"
    assert result2 == "ok"
    assert counter["calls"] == 1

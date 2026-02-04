import asyncio
import uuid

from github_mcp.mcp_server import decorators


def test_async_dedupe_caches_result_within_loop():
    key = f"dedupe-{uuid.uuid4()}"
    counter = {"calls": 0}

    async def _work():
        counter["calls"] += 1
        return "ok"

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result1 = loop.run_until_complete(decorators._maybe_dedupe_call(key, _work))
        result2 = loop.run_until_complete(decorators._maybe_dedupe_call(key, _work))
    finally:
        loop.close()
        asyncio.set_event_loop(None)

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


def test_clear_read_dedupe_caches_removes_read_entries():
    req = {"session_id": "s1", "message_id": "m1"}
    read_key = decorators._dedupe_key(
        tool_name="read_tool",
        write_action=False,
        req=req,
        args={"path": "README.md"},
    )
    write_key = decorators._dedupe_key(
        tool_name="write_tool",
        write_action=True,
        req=req,
        args={"path": "README.md", "content": "hi"},
    )

    decorators._DEDUPE_SYNC_CACHE[read_key] = (999999.0, {"status": "ok"})
    decorators._DEDUPE_SYNC_CACHE[write_key] = (999999.0, {"status": "ok"})

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        async_key = (id(loop), read_key)
        decorators._DEDUPE_ASYNC_CACHE[async_key] = (999999.0, loop.create_future())
        decorators._clear_read_dedupe_caches()
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    assert read_key not in decorators._DEDUPE_SYNC_CACHE
    assert async_key not in decorators._DEDUPE_ASYNC_CACHE
    assert write_key in decorators._DEDUPE_SYNC_CACHE

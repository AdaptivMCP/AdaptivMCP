import asyncio
import threading


def test_active_event_loop_creates_new_when_closed(monkeypatch):
    from github_mcp import async_utils

    closed_loop = asyncio.new_event_loop()
    closed_loop.close()

    # Simulate no running loop and a closed default loop.
    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: (_ for _ in ()).throw(RuntimeError()),
    )
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: closed_loop)

    loop = async_utils.active_event_loop()
    assert isinstance(loop, asyncio.AbstractEventLoop)
    assert loop.is_closed() is False


def test_schedule_close_runs_client_loop_in_sync_context():
    from github_mcp import async_utils

    class DummyClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    client = DummyClient()
    loop = asyncio.new_event_loop()
    try:
        async_utils._schedule_close(client, client_loop=loop)
        assert client.closed is True
    finally:
        loop.close()


def test_schedule_close_call_soon_threadsafe_path():
    from github_mcp import async_utils

    class DummyClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    client = DummyClient()
    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

    try:
        async_utils._schedule_close(client, client_loop=loop)
        # Give the event loop a chance to execute the scheduled task.
        for _ in range(100):
            if client.closed:
                break
            asyncio.run(asyncio.sleep(0.001))
        assert client.closed is True
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()


def test_schedule_close_fallback_asyncio_run_used_when_no_loop_running(monkeypatch):
    from github_mcp import async_utils

    class DummyClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    client = DummyClient()
    called = {"ran": False}

    def fake_run(coro):
        called["ran"] = True
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr(asyncio, "run", fake_run)

    async_utils._schedule_close(client, client_loop=None)

    assert called["ran"] is True
    assert client.closed is True


def test_schedule_close_ignores_already_closed_client():
    from github_mcp import async_utils

    class DummyClient:
        is_closed = True

        async def aclose(self):
            raise AssertionError("should not be called")

    async_utils._schedule_close(DummyClient(), client_loop=None)

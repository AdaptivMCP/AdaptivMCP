from __future__ import annotations

import asyncio

import pytest


def test_jitter_sleep_seconds_returns_zero_for_bad_inputs(monkeypatch):
    from github_mcp.retry_utils import jitter_sleep_seconds

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    assert jitter_sleep_seconds(-1) == 0.0
    assert jitter_sleep_seconds(0) == 0.0
    assert jitter_sleep_seconds("nope") == 0.0  # type: ignore[arg-type]


def test_jitter_sleep_seconds_deterministic_under_pytest(monkeypatch):
    from github_mcp import retry_utils

    called: list[tuple[float, float]] = []

    def _uniform(a: float, b: float) -> float:
        called.append((a, b))
        return b

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.setattr(retry_utils.random, "uniform", _uniform)

    # Under pytest, jitter is disabled for determinism.
    assert retry_utils.jitter_sleep_seconds(1.25, respect_min=True) == 1.25
    assert retry_utils.jitter_sleep_seconds(2.0, respect_min=False) == 2.0
    assert called == []


def test_jitter_sleep_seconds_full_jitter(monkeypatch):
    from github_mcp import retry_utils

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def _uniform(a: float, b: float) -> float:
        assert a == 0.0
        assert b == 4.0
        return 1.5

    monkeypatch.setattr(retry_utils.random, "uniform", _uniform)
    assert retry_utils.jitter_sleep_seconds(4.0, respect_min=False) == 1.5


def test_jitter_sleep_seconds_respects_min_and_caps(monkeypatch):
    from github_mcp import retry_utils

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # When respect_min=True, jitter is added after the minimum and capped.
    # For delay=10 and cap_seconds=1, jitter upper bound is min(1, 10*0.25)=1.
    def _uniform(a: float, b: float) -> float:
        assert a == 0.0
        assert b == 1.0
        return 0.25

    monkeypatch.setattr(retry_utils.random, "uniform", _uniform)
    assert (
        retry_utils.jitter_sleep_seconds(10.0, respect_min=True, cap_seconds=1.0)
        == 10.25
    )


@pytest.mark.asyncio
async def test_schedule_close_does_not_call_asyncio_run_in_async_context(monkeypatch):
    from github_mcp import async_utils

    messages: list[str] = []

    class _Client:
        is_closed = False

        async def aclose(self) -> None:
            return None

    # Force create_task scheduling to fail.
    monkeypatch.setattr(
        asyncio,
        "create_task",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
    )

    # Ensure asyncio.run is not used from an async context.
    def _boom(*args, **kwargs):
        raise AssertionError("asyncio.run should not be called from async context")

    monkeypatch.setattr(asyncio, "run", _boom)

    async_utils._schedule_close(
        _Client(),
        client_loop=None,
        log_debug=messages.append,
    )

    assert any("cannot call asyncio.run" in msg for msg in messages)


def test_active_event_loop_creates_loop_when_get_event_loop_raises(monkeypatch):
    from github_mcp import async_utils

    class _Loop(asyncio.AbstractEventLoop):
        # Minimal stub for identity checks.
        def run_forever(self):
            raise NotImplementedError

        def run_until_complete(self, future):
            raise NotImplementedError

        def stop(self):
            raise NotImplementedError

        def is_running(self):
            return False

        def is_closed(self):
            return False

        def close(self):
            raise NotImplementedError

        def create_task(self, coro, *, name=None, context=None):
            raise NotImplementedError

        def call_soon(self, callback, *args, context=None):
            raise NotImplementedError

        def call_later(self, delay, callback, *args, context=None):
            raise NotImplementedError

        def call_at(self, when, callback, *args, context=None):
            raise NotImplementedError

        def time(self):
            return 0.0

        def get_debug(self):
            return False

        def set_debug(self, enabled):
            raise NotImplementedError

        def get_exception_handler(self):
            return None

        def set_exception_handler(self, handler):
            raise NotImplementedError

        def default_exception_handler(self, context):
            raise NotImplementedError

        def call_exception_handler(self, context):
            raise NotImplementedError

        def get_task_factory(self):
            return None

        def set_task_factory(self, factory):
            raise NotImplementedError

        def get_signal_handler(self, sig):
            return None

        def add_signal_handler(self, sig, callback, *args):
            raise NotImplementedError

        def remove_signal_handler(self, sig):
            raise NotImplementedError

        def add_reader(self, fd, callback, *args):
            raise NotImplementedError

        def remove_reader(self, fd):
            raise NotImplementedError

        def add_writer(self, fd, callback, *args):
            raise NotImplementedError

        def remove_writer(self, fd):
            raise NotImplementedError

        def sock_recv(self, sock, nbytes):
            raise NotImplementedError

        def sock_sendall(self, sock, data):
            raise NotImplementedError

        def sock_connect(self, sock, address):
            raise NotImplementedError

        def sock_accept(self, sock):
            raise NotImplementedError

        def sock_sendfile(self, sock, file, offset=0, count=None, *, fallback=True):
            raise NotImplementedError

        def create_future(self):
            raise NotImplementedError

        def get_iteration(self):
            raise NotImplementedError

        def shutdown_asyncgens(self):
            raise NotImplementedError

        def shutdown_default_executor(self):
            raise NotImplementedError

    sentinel = _Loop()
    set_called: list[asyncio.AbstractEventLoop] = []

    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: (_ for _ in ()).throw(RuntimeError("no running loop")),
    )
    monkeypatch.setattr(
        asyncio,
        "get_event_loop",
        lambda: (_ for _ in ()).throw(RuntimeError("no loop")),
    )
    monkeypatch.setattr(asyncio, "new_event_loop", lambda: sentinel)
    monkeypatch.setattr(asyncio, "set_event_loop", lambda loop: set_called.append(loop))

    out = async_utils.active_event_loop()
    assert out is sentinel
    assert set_called == [sentinel]

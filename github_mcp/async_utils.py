"""Asyncio helpers shared across modules.

Connector environments can swap event loops after idle periods. These helpers
provide defensive utilities to keep long-lived resources (like httpx clients)
bound to the active loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


def active_event_loop() -> asyncio.AbstractEventLoop:
    """Return a usable asyncio event loop.

    In Python 3.12+, ``asyncio.get_event_loop()`` may raise when no loop has been
    set for the current thread. This helper prefers the running loop (when in an
    async context) and otherwise ensures a loop exists for sync contexts.
    """

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("event loop is closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _schedule_close(
    client: Any,
    *,
    client_loop: asyncio.AbstractEventLoop | None,
    log_debug: Callable[[str], None] | None = None,
    log_debug_exc: Callable[[str], None] | None = None,
) -> None:
    """Best-effort close for async clients across loop contexts."""

    if client is None:
        return

    try:
        if getattr(client, "is_closed", False):
            return
    except Exception:  # nosec B110
        # If we cannot interrogate the client state, attempt to close anyway.
        pass

    try:
        running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    def _log(msg: str) -> None:
        if log_debug_exc is not None:
            log_debug_exc(msg)
        elif log_debug is not None:
            log_debug(msg)

    def _schedule_on_running_loop() -> bool:
        coro = None
        try:
            # Avoid leaking un-awaited coroutine objects if task creation fails.
            coro = client.aclose()
            task = asyncio.create_task(coro)
            del task
            return True
        except Exception:
            try:
                if coro is not None and hasattr(coro, "close"):
                    coro.close()
            except Exception:  # nosec B110
                pass
            return False

    def _try_client_loop() -> bool:
        if client_loop is None or client_loop.is_closed():
            return False

        # Prefer closing on the loop the client was created on.
        if client_loop.is_running():
            # If we're already on that loop, schedule directly; otherwise, hop threads.
            if running_loop is client_loop:
                if _schedule_on_running_loop():
                    return True
                _log("Failed to schedule client close on running client loop")
                return False

            try:
                client_loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(client.aclose())
                )
                return True
            except Exception:
                _log("Failed to schedule client close via call_soon_threadsafe")
                return False

        # Sync context: we can drive the loop to completion.
        if running_loop is None:
            try:
                client_loop.run_until_complete(client.aclose())
                return True
            except Exception:
                _log("Failed to close async client by running its loop")
                return False

        # Async context: we cannot run another loop; schedule on current loop best-effort.
        if _schedule_on_running_loop():
            return True
        _log("Failed to schedule async client close from async context")
        return False

    closed = False

    # Strategy 1: close on client loop if available.
    if _try_client_loop():
        closed = True

    # Strategy 2: schedule on current running loop.
    if not closed and running_loop is not None:
        if _schedule_on_running_loop():
            closed = True
        else:
            _log("Failed to schedule async client close on current running loop")

    # Strategy 3: final fallback using asyncio.run.
    if not closed:
        # Only safe when no event loop is running in this thread.
        if running_loop is None:
            try:
                asyncio.run(client.aclose())
            except Exception:
                _log("Failed to close async client in fallback asyncio.run")
        else:
            _log(
                "Failed to close async client: cannot call asyncio.run from async context"
            )


def refresh_async_client(  # noqa: PLR0913
    client: Any | None,
    *,
    client_loop: asyncio.AbstractEventLoop | None,
    rebuild: Callable[[], Any],
    force_refresh: bool = False,
    log_debug: Callable[[str], None] | None = None,
    log_debug_exc: Callable[[str], None] | None = None,
) -> tuple[Any, asyncio.AbstractEventLoop]:
    """Return a loop-safe async client, rebuilding if necessary.

    The underlying event loop may change after idle periods in connector
    environments. Recreate the client when the loop differs or the client is
    already closed so outbound requests stay bound to the active loop.

    Logging is best-effort: callers may pass ``log_debug`` and
    ``log_debug_exc`` hooks.
    """

    loop = active_event_loop()

    needs_refresh = force_refresh or client is None
    if not needs_refresh:
        try:
            needs_refresh = bool(getattr(client, "is_closed", False))
        except Exception:
            needs_refresh = True

    if not needs_refresh and client_loop is not None and client_loop is not loop:
        needs_refresh = True

    if not needs_refresh:
        # `client` is non-None here.
        return client, client_loop or loop

    try:
        _schedule_close(
            client,
            client_loop=client_loop,
            log_debug=log_debug,
            log_debug_exc=log_debug_exc,
        )
    except Exception:
        if log_debug_exc is not None:
            log_debug_exc("Failed to refresh async client")
        elif log_debug is not None:
            log_debug("Failed to refresh async client")

    fresh_client = rebuild()
    return fresh_client, loop


__all__ = ["active_event_loop", "refresh_async_client"]

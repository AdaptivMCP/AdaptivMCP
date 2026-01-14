"""Asyncio helpers shared across modules.

Connector environments can swap event loops after idle periods. These helpers
provide defensive utilities to keep long-lived resources (like httpx clients)
bound to the active loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional, Tuple


def active_event_loop() -> asyncio.AbstractEventLoop:
    """Return a usable asyncio event loop.

    In Python 3.11+, ``asyncio.get_event_loop()`` may raise when no loop has been
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
    client_loop: Optional[asyncio.AbstractEventLoop],
    current_loop: asyncio.AbstractEventLoop,
    log_debug: Optional[Callable[[str], None]] = None,
    log_debug_exc: Optional[Callable[[str], None]] = None,
) -> None:
    if client is None:
        return

    try:
        if getattr(client, "is_closed", False):
            return
    except Exception:
        # If we cannot interrogate the client state, attempt to close anyway.
        pass

    running_loop: Optional[asyncio.AbstractEventLoop] = None
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    def _log(msg: str) -> None:
        if log_debug_exc is not None:
            log_debug_exc(msg)
        elif log_debug is not None:
            log_debug(msg)

    # Prefer closing on the loop the client was created on.
    if client_loop is not None and not client_loop.is_closed():
        if client_loop.is_running():
            # If we're already on that loop, schedule directly; otherwise, hop threads.
            if running_loop is client_loop:
                try:
                    asyncio.create_task(client.aclose())
                    return
                except Exception:
                    _log("Failed to schedule client close on running client loop")
                    return
            try:
                client_loop.call_soon_threadsafe(lambda: asyncio.create_task(client.aclose()))
                return
            except Exception:
                _log("Failed to schedule client close via call_soon_threadsafe")
                # Fall through to best-effort options.
        else:
            # Sync context: we can drive the loop to completion.
            if running_loop is None:
                try:
                    client_loop.run_until_complete(client.aclose())
                    return
                except Exception:
                    _log("Failed to close async client by running its loop")
            else:
                # Async context: we cannot run another loop; try current loop best-effort.
                try:
                    asyncio.create_task(client.aclose())
                    return
                except Exception:
                    _log("Failed to schedule async client close from async context")
                    return

    # Fallback: close on the current loop if possible.
    if running_loop is not None:
        try:
            asyncio.create_task(client.aclose())
            return
        except Exception:
            _log("Failed to schedule async client close on current running loop")
            return

    # Final fallback: create a temporary loop to close the client.
    try:
        asyncio.run(client.aclose())
    except Exception:
        _log("Failed to close async client in fallback asyncio.run")


def refresh_async_client(
    client: Optional[Any],
    *,
    client_loop: Optional[asyncio.AbstractEventLoop],
    rebuild: Callable[[], Any],
    force_refresh: bool = False,
    log_debug: Optional[Callable[[str], None]] = None,
    log_debug_exc: Optional[Callable[[str], None]] = None,
) -> Tuple[Any, asyncio.AbstractEventLoop]:
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
            if getattr(client, "is_closed", False):
                needs_refresh = True
        except Exception:
            needs_refresh = True

    if not needs_refresh and client_loop is not None and client_loop is not loop:
        needs_refresh = True

    if not needs_refresh:
        # `client` should be non-None here because `needs_refresh` is false.
        if client is None:
            needs_refresh = True
        else:
            return client, client_loop or loop

    try:
        _schedule_close(
            client,
            client_loop=client_loop,
            current_loop=loop,
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

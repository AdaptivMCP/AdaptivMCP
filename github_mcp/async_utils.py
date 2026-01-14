"""Asyncio helpers shared across modules.

Connector environments can swap event loops after idle periods. These helpers
provide defensive utilities to keep long-lived resources (like httpx clients)
bound to the active loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional, Tuple


def active_event_loop() -> asyncio.AbstractEventLoop:
    """Return the active asyncio event loop, tolerant of missing running loop."""

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


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
        if client is not None and not getattr(client, "is_closed", False):
            if client_loop is not None and not client_loop.is_closed():
                client_loop.create_task(client.aclose())
            else:
                # Best-effort shutdown without assuming an active running loop.
                try:
                    loop.create_task(client.aclose())
                except Exception:
                    try:
                        if not loop.is_closed() and not loop.is_running():
                            loop.run_until_complete(client.aclose())
                        else:
                            asyncio.run(client.aclose())
                    except Exception:
                        if log_debug_exc is not None:
                            log_debug_exc("Failed to close async client during refresh")
                        elif log_debug is not None:
                            log_debug("Failed to close async client during refresh")
    except Exception:
        if log_debug_exc is not None:
            log_debug_exc("Failed to refresh async client")
        elif log_debug is not None:
            log_debug("Failed to refresh async client")

    fresh_client = rebuild()
    return fresh_client, loop


__all__ = ["active_event_loop", "refresh_async_client"]

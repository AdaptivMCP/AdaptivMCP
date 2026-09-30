"""Session-scoped workspace identity and concurrency leases."""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


def _request_identity() -> tuple[str, str]:
    try:
        from github_mcp.mcp_server.context import get_request_context
        context = get_request_context()
    except Exception:
        context = {}
    principal = str(context.get("principal") or "")
    if not principal:
        # Internal callers outside HTTP transport remain isolated by process.
        principal = f"internal-pid:{os.getpid()}"
    session = str(context.get("session_id") or context.get("request_id") or "")
    if not session:
        session = f"internal-{os.getpid()}"
    return principal, session


def workspace_identity_key() -> str:
    principal, session = _request_identity()
    return hashlib.sha256(
        f"{principal}\x00{session}".encode("utf-8")
    ).hexdigest()[:32]


def workspace_identity_path(base_dir: str, full_name: str, ref: str) -> str:
    repo_key = full_name.replace("/", "__")
    return os.path.join(
        base_dir, repo_key, ".sessions", workspace_identity_key(), ref
    )


async def _get_lock(path: str) -> asyncio.Lock:
    key = os.path.realpath(path)
    async with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[key] = lock
        return lock


@asynccontextmanager
async def workspace_lease(
    workspace_dir: str, *, timeout_seconds: float | int = 0
) -> AsyncIterator[dict[str, Any]]:
    """Serialize operations that share one session-scoped workspace."""
    lock = await _get_lock(workspace_dir)
    timeout = float(timeout_seconds or 0)
    started = time.monotonic()
    if timeout > 0:
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
    else:
        await lock.acquire()
    try:
        yield {
            "workspace": os.path.realpath(workspace_dir),
            "identity": workspace_identity_key(),
            "wait_seconds": max(0.0, time.monotonic() - started),
        }
    finally:
        lock.release()


__all__ = ["workspace_identity_key", "workspace_identity_path", "workspace_lease"]

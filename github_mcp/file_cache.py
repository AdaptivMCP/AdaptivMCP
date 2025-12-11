"""In-process cache for fetched GitHub file contents.

The cache is intentionally lightweight: it keeps decoded file payloads in
memory for the lifetime of the process so assistants can rehydrate context
without re-fetching from GitHub on every tool call. Entries are evicted using
an LRU policy when the cache exceeds configured entry or byte limits.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Dict, Iterable, Optional, Tuple

from . import config


class FileCache:
    """Simple LRU cache for GitHub file payloads."""

    def __init__(self, max_entries: int, max_bytes: int):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._cache: "OrderedDict[str, Dict]" = OrderedDict()
        self._current_bytes = 0

    def _evict_if_needed(self) -> None:
        while self.max_entries > 0 and len(self._cache) > self.max_entries:
            _, evicted = self._cache.popitem(last=False)
            self._current_bytes -= evicted.get("size_bytes", 0)

        while self.max_bytes > 0 and self._current_bytes > self.max_bytes:
            _, evicted = self._cache.popitem(last=False)
            self._current_bytes -= evicted.get("size_bytes", 0)

    def put(self, key: str, value: Dict) -> None:
        """Insert ``value`` keyed by ``key`` and evict if over limits."""

        if key in self._cache:
            existing = self._cache.pop(key)
            self._current_bytes -= existing.get("size_bytes", 0)

        self._cache[key] = value
        self._cache.move_to_end(key)
        self._current_bytes += value.get("size_bytes", 0)
        self._evict_if_needed()

    def get(self, key: str) -> Optional[Dict]:
        item = self._cache.get(key)
        if item is None:
            return None
        self._cache.move_to_end(key)
        return item

    def bulk_get(self, keys: Iterable[str]) -> Dict[str, Dict]:
        results: Dict[str, Dict] = {}
        for key in keys:
            item = self.get(key)
            if item is not None:
                results[key] = item
        return results

    def clear(self) -> None:
        self._cache.clear()
        self._current_bytes = 0

    def stats(self) -> Dict[str, int]:
        return {
            "entries": len(self._cache),
            "bytes": self._current_bytes,
            "max_entries": self.max_entries,
            "max_bytes": self.max_bytes,
        }


FILE_CACHE = FileCache(
    max_entries=config.FILE_CACHE_MAX_ENTRIES,
    max_bytes=config.FILE_CACHE_MAX_BYTES,
)


def cache_key(full_name: str, ref: str, path: str) -> str:
    return "|".join([full_name, ref, path])


def cache_payload(
    *,
    full_name: str,
    ref: str,
    path: str,
    decoded: Dict,
) -> Dict:
    size_bytes = 0
    decoded_bytes = decoded.get("decoded_bytes")
    if isinstance(decoded_bytes, (bytes, bytearray)):
        size_bytes = len(decoded_bytes)

    entry = {
        **decoded,
        "cached_at": time.time(),
        "full_name": full_name,
        "ref": ref,
        "path": path,
        "size_bytes": size_bytes,
        "sha": decoded.get("sha") or decoded.get("json", {}).get("sha"),
    }
    FILE_CACHE.put(cache_key(full_name, ref, path), entry)
    return entry


def get_cached(full_name: str, ref: str, path: str) -> Optional[Dict]:
    return FILE_CACHE.get(cache_key(full_name, ref, path))


def bulk_get_cached(full_name: str, ref: str, paths: Iterable[str]) -> Dict[str, Dict]:
    keys = [cache_key(full_name, ref, path) for path in paths]
    entries = FILE_CACHE.bulk_get(keys)
    # Map back to paths for easier consumption by callers.
    reverse_lookup = {cache_key(full_name, ref, path): path for path in paths}
    return {reverse_lookup[k]: v for k, v in entries.items() if k in reverse_lookup}


def clear_cache() -> None:
    FILE_CACHE.clear()


def cache_stats() -> Dict[str, int]:
    return FILE_CACHE.stats()


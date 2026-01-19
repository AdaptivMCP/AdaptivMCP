from __future__ import annotations

import time

import pytest

import github_mcp.file_cache as fc


def test_file_cache_evicts_lru_by_entry_count() -> None:
    cache = fc.FileCache(max_entries=2, max_bytes=0)
    cache.put("a", {"size_bytes": 1})
    cache.put("b", {"size_bytes": 1})
    cache.put("c", {"size_bytes": 1})

    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None


def test_file_cache_get_marks_item_as_recent() -> None:
    cache = fc.FileCache(max_entries=2, max_bytes=0)
    cache.put("a", {"size_bytes": 1})
    cache.put("b", {"size_bytes": 1})

    # Touch 'a' so 'b' is the least-recently used entry.
    assert cache.get("a") is not None
    cache.put("c", {"size_bytes": 1})

    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


def test_file_cache_evicts_by_byte_budget() -> None:
    cache = fc.FileCache(max_entries=0, max_bytes=5)
    cache.put("a", {"size_bytes": 4})
    cache.put("b", {"size_bytes": 4})

    # After inserting b, the cache should evict the oldest ('a') to satisfy the byte cap.
    assert cache.get("a") is None
    assert cache.get("b") is not None

    cache.put("c", {"size_bytes": 4})
    assert cache.get("b") is None
    assert cache.get("c") is not None


def test_cache_payload_records_metadata_and_size(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = fc.FileCache(max_entries=10, max_bytes=10_000)
    monkeypatch.setattr(fc, "FILE_CACHE", cache)

    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)

    decoded = {"decoded_bytes": b"hello", "json": {"sha": "abc"}}
    entry = fc.cache_payload(full_name="o/r", ref="main", path="README.md", decoded=decoded)

    assert entry["size_bytes"] == 5
    assert entry["sha"] == "abc"
    assert entry["cached_at"] == now
    assert fc.get_cached("o/r", "main", "README.md") is entry


def test_bulk_get_cached_maps_back_to_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = fc.FileCache(max_entries=10, max_bytes=10_000)
    monkeypatch.setattr(fc, "FILE_CACHE", cache)

    fc.cache_payload(
        full_name="o/r",
        ref="main",
        path="a.txt",
        decoded={"decoded_bytes": b"a"},
    )
    fc.cache_payload(
        full_name="o/r",
        ref="main",
        path="b.txt",
        decoded={"decoded_bytes": b"b"},
    )

    hits = fc.bulk_get_cached("o/r", "main", ["a.txt", "missing.txt", "b.txt"])
    assert set(hits) == {"a.txt", "b.txt"}
    assert hits["a.txt"]["decoded_bytes"] == b"a"
    assert hits["b.txt"]["decoded_bytes"] == b"b"

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_cache_files_uses_existing_cache_when_refresh_false(monkeypatch):
    """Cover cache_files short-circuit and payload decoration."""

    from github_mcp.main_tools import content_cache

    # Keep paths stable/easy to reason about.
    monkeypatch.setattr(content_cache, "_normalize_repo_path_for_repo", lambda _full, p: p)

    async def _fake_resolve(_full_name: str, _ref: str | None):
        return {"requested_ref": "main", "resolved_ref": "sha-1", "tree_sha": None}

    monkeypatch.setattr(content_cache, "_resolve_ref_snapshot", _fake_resolve)

    cached_existing = {
        "a.txt": {"full_name": "o/r", "ref": "sha-1", "path": "a.txt", "decoded": {"t": "cached"}},
    }

    monkeypatch.setattr(content_cache, "bulk_get_cached", lambda *_args, **_kwargs: cached_existing)
    monkeypatch.setattr(content_cache, "cache_stats", lambda: {"entries": 1})

    decode_calls: list[str] = []

    async def _fake_decode(_full: str, p: str, _ref: str | None):
        decode_calls.append(p)
        return {"decoded": p}

    monkeypatch.setattr(content_cache, "_decode", _fake_decode)

    cache_payload_calls: list[str] = []

    def _fake_cache_payload(*, full_name: str, ref: str, path: str, decoded: dict):
        cache_payload_calls.append(path)
        return {"full_name": full_name, "ref": ref, "path": path, "decoded": decoded}

    monkeypatch.setattr(content_cache, "cache_payload", _fake_cache_payload)

    out = await content_cache.cache_files("o/r", ["a.txt", "b.txt"], ref="main", refresh=False)

    assert out["resolved_ref"] == "sha-1"
    assert out["files"]["a.txt"]["cached"] is True
    assert out["files"]["a.txt"]["decoded"]["t"] == "cached"

    # Only the missing file should be decoded and cached.
    assert decode_calls == ["b.txt"]
    assert cache_payload_calls == ["b.txt"]

    b = out["files"]["b.txt"]
    assert b["cached"] is False
    assert b["decoded"]["requested_ref"] == "main"
    assert b["decoded"]["resolved_ref"] == "sha-1"


@pytest.mark.asyncio
async def test_list_repository_tree_filters_and_normalizes_prefix(monkeypatch):
    """Cover list_repository_tree filtering, prefix handling, and type selection."""

    from github_mcp.main_tools import content_cache

    async def _fake_resolve(_full_name: str, _ref: str | None):
        return {"requested_ref": "main", "resolved_ref": "sha-1", "tree_sha": "tree-sha"}

    monkeypatch.setattr(content_cache, "_resolve_ref_snapshot", _fake_resolve)

    # Make normalization visible.
    monkeypatch.setattr(
        content_cache,
        "_normalize_repo_path_for_repo",
        lambda _full, p: p.replace("\\", "/").lstrip("/"),
    )

    async def _fake_github_request(method: str, path: str, params=None):
        assert method == "GET"
        # Tool should use tree sha for lookup.
        assert path.endswith("/git/trees/tree-sha")
        assert params == {"recursive": 1}
        return {
            "json": {
                "sha": "tree-sha",
                "tree": [
                    {
                        "path": "src/app.py",
                        "type": "blob",
                        "mode": "100644",
                        "size": 12,
                        "sha": "a",
                    },
                    {"path": "src/pkg", "type": "tree", "mode": "040000", "sha": "b"},
                    {
                        "path": "docs/readme.md",
                        "type": "blob",
                        "mode": "100644",
                        "size": 5,
                        "sha": "c",
                    },
                    {"path": "ignored", "type": "commit", "sha": "d"},
                    "not-a-dict",
                ],
            }
        }

    monkeypatch.setattr(content_cache, "_github_request", _fake_github_request)

    # Prefix '.' should be treated as root (no filtering).
    out_root = await content_cache.list_repository_tree(
        "o/r",
        ref="main",
        path_prefix=".",
        include_blobs=True,
        include_trees=True,
    )

    assert out_root["entry_count"] == 3
    assert {e["path"] for e in out_root["entries"]} == {"src/app.py", "src/pkg", "docs/readme.md"}

    # Now filter to only src/*.
    out_src = await content_cache.list_repository_tree(
        "o/r",
        ref="main",
        path_prefix="/src",
        include_blobs=True,
        include_trees=True,
    )
    assert out_src["entry_count"] == 2
    assert {e["path"] for e in out_src["entries"]} == {"src/app.py", "src/pkg"}


@pytest.mark.asyncio
async def test_list_repository_tree_returns_empty_when_types_excluded(monkeypatch):
    from github_mcp.main_tools import content_cache

    async def _fake_resolve(_full_name: str, _ref: str | None):
        return {"requested_ref": "main", "resolved_ref": "sha-1", "tree_sha": "tree-sha"}

    monkeypatch.setattr(content_cache, "_resolve_ref_snapshot", _fake_resolve)

    async def _fake_github_request(method: str, path: str, params=None):
        return {"json": {"sha": "tree-sha", "tree": [{"path": "a", "type": "blob", "sha": "x"}]}}

    monkeypatch.setattr(content_cache, "_github_request", _fake_github_request)

    out = await content_cache.list_repository_tree(
        "o/r",
        ref="main",
        include_blobs=False,
        include_trees=False,
    )

    assert out["entries"] == []
    assert out["entry_count"] == 0
    assert "Both blobs and trees were excluded" in out["message"]

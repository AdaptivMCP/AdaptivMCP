from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from github_mcp.config import FETCH_FILES_CONCURRENCY
from github_mcp.exceptions import GitHubAPIError
from github_mcp.file_cache import bulk_get_cached, cache_payload, cache_stats
from github_mcp.server import _github_request, _structured_tool_error
from github_mcp.utils import _effective_ref_for_repo, _normalize_repo_path_for_repo
import sys

from github_mcp.github_content import _decode_github_content as _decode_default


def _cache_file_result(
    *, full_name: str, path: str, ref: str, decoded: Dict[str, Any]
) -> Dict[str, Any]:
    normalized_path = _normalize_repo_path_for_repo(full_name, path)
    effective_ref = _effective_ref_for_repo(full_name, ref)
    return cache_payload(
        full_name=full_name,
        ref=effective_ref,
        path=normalized_path,
        decoded=decoded,
    )


async def _decode(full_name: str, path: str, ref: str | None) -> Dict[str, Any]:
    """Resolve decode function, preferring monkeypatched main._decode_github_content."""

    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    fn = (
        getattr(main_mod, "_decode_github_content", _decode_default)
        if main_mod
        else _decode_default
    )
    return await fn(full_name, path, ref)


async def fetch_files(full_name: str, paths: List[str], ref: str = "main") -> Dict[str, Any]:
    """Fetch multiple files concurrently with per-file error isolation."""

    results: Dict[str, Any] = {}
    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _fetch_single(p: str) -> None:
        normalized_path = _normalize_repo_path_for_repo(full_name, p)
        async with sem:
            try:
                decoded = await _decode(full_name, normalized_path, ref)
                cached = _cache_file_result(
                    full_name=full_name,
                    path=normalized_path,
                    ref=ref,
                    decoded=decoded,
                )
                results[p] = cached
            except Exception as e:
                results[p] = _structured_tool_error(
                    e,
                    context="fetch_files",
                    path=p,
                )

    await asyncio.gather(*[_fetch_single(p) for p in paths])
    return {"files": results}


async def get_cached_files(full_name: str, paths: List[str], ref: str = "main") -> Dict[str, Any]:
    """Return cached file entries and list any missing paths."""

    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_paths = [_normalize_repo_path_for_repo(full_name, p) for p in paths]
    cached = bulk_get_cached(full_name, effective_ref, normalized_paths)
    missing = [p for p in normalized_paths if p not in cached]

    return {
        "full_name": full_name,
        "ref": effective_ref,
        "files": cached,
        "missing": missing,
        "cache": cache_stats(),
    }


async def cache_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch files and store them in the in-process cache."""

    results: Dict[str, Any] = {}
    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_paths = [_normalize_repo_path_for_repo(full_name, p) for p in paths]

    cached_existing: Dict[str, Any] = {}
    if not refresh:
        cached_existing = bulk_get_cached(full_name, effective_ref, normalized_paths)

    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _cache_single(p: str) -> None:
        async with sem:
            if not refresh and p in cached_existing:
                results[p] = {**cached_existing[p], "cached": True}
                return

            decoded = await _decode(full_name, p, effective_ref)
            cached = cache_payload(
                full_name=full_name,
                ref=effective_ref,
                path=p,
                decoded=decoded,
            )
            results[p] = {**cached, "cached": False}

    await asyncio.gather(*[_cache_single(p) for p in normalized_paths])

    return {
        "full_name": full_name,
        "ref": effective_ref,
        "files": results,
        "cache": cache_stats(),
    }


async def list_repository_tree(
    full_name: str,
    ref: str = "main",
    path_prefix: Optional[str] = None,
    recursive: bool = True,
    max_entries: int = 1000,
    include_blobs: bool = True,
    include_trees: bool = True,
) -> Dict[str, Any]:
    """List files and folders in a repository tree with optional filtering."""

    if max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")

    params = {"recursive": 1 if recursive else 0}
    data = await _github_request("GET", f"/repos/{full_name}/git/trees/{ref}", params=params)

    payload = data.get("json") or {}
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise GitHubAPIError("Unexpected tree response from GitHub")

    allowed_types = set()
    if include_blobs:
        allowed_types.add("blob")
    if include_trees:
        allowed_types.add("tree")
    if not allowed_types:
        return {
            "entries": [],
            "entry_count": 0,
            "truncated": False,
            "message": "Both blobs and trees were excluded; nothing to return.",
        }

    normalized_prefix = None
    if isinstance(path_prefix, str):
        candidate = path_prefix.strip().replace("\\", "/")
        # Treat common "root" markers as no prefix.
        if candidate in {"", "/", ".", "./"}:
            normalized_prefix = None
        else:
            normalized_prefix = candidate.lstrip("/")

    filtered_entries: List[Dict[str, Any]] = []
    for entry in tree:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        if entry_type not in allowed_types:
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if normalized_prefix and not path.startswith(normalized_prefix):
            continue

        normalized_path = _normalize_repo_path_for_repo(full_name, path)

        filtered_entries.append(
            {
                "path": normalized_path,
                "type": entry_type,
                "mode": entry.get("mode"),
                "size": entry.get("size"),
                "sha": entry.get("sha"),
            }
        )

    truncated = len(filtered_entries) > max_entries
    return {
        "ref": payload.get("sha") or ref,
        "entry_count": len(filtered_entries),
        "truncated": truncated,
        "entries": filtered_entries[:max_entries],
    }

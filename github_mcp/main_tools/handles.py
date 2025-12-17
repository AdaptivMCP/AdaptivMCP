"""Lightweight handle resolution (issue/PR/branch handles).

Tool implementations for the main MCP surface.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ._main import _main


async def resolve_handle(full_name: str, handle: str) -> Dict[str, Any]:
    """Resolve a lightweight GitHub handle into issue, PR, or branch details."""

    m = _main()

    original_handle = handle
    handle = handle.strip()
    lower_handle = handle.lower()

    resolved_kinds: list[str] = []
    issue: Optional[Dict[str, Any]] = None
    pull_request: Optional[Dict[str, Any]] = None
    branch: Optional[Dict[str, Any]] = None

    def _append_kind(name: str, value: Optional[Dict[str, Any]]):
        if value is not None:
            resolved_kinds.append(name)

    async def _try_fetch_issue(number: int) -> Optional[Dict[str, Any]]:
        try:
            result = await m.fetch_issue(full_name, number)
        except Exception:
            return None
        normalize = getattr(m, "_normalize_issue_payload", None)
        if callable(normalize):
            return normalize(result)
        return result if isinstance(result, dict) else None

    async def _try_fetch_pr(number: int) -> Optional[Dict[str, Any]]:
        try:
            result = await m.fetch_pr(full_name, number)
        except Exception:
            return None
        normalize = getattr(m, "_normalize_pr_payload", None)
        if callable(normalize):
            return normalize(result)
        return result if isinstance(result, dict) else None

    async def _try_fetch_branch(name: str) -> Optional[Dict[str, Any]]:
        try:
            result = await m.get_branch_summary(full_name, name)
        except Exception:
            return None
        normalize = getattr(m, "_normalize_branch_summary", None)
        if callable(normalize):
            return normalize(result)
        return result if isinstance(result, dict) else None

    def _parse_int(value: str) -> Optional[int]:
        value = value.strip()
        if not value.isdigit():
            return None
        try:
            return int(value)
        except ValueError:
            return None

    number: Optional[int] = None

    if lower_handle.startswith("issue:"):
        number = _parse_int(handle.split(":", 1)[1])
        if number is not None:
            issue = await _try_fetch_issue(number)
            _append_kind("issue", issue)
    elif lower_handle.startswith("pr:"):
        number = _parse_int(handle.split(":", 1)[1])
        if number is not None:
            pull_request = await _try_fetch_pr(number)
            _append_kind("pull_request", pull_request)
    else:
        numeric_match = re.fullmatch(r"#?(\d+)", handle)
        trailing_match = re.search(r"#(\d+)$", handle)
        if numeric_match:
            number = int(numeric_match.group(1))
        elif trailing_match:
            number = int(trailing_match.group(1))

        if number is not None:
            issue = await _try_fetch_issue(number)
            _append_kind("issue", issue)

            pull_request = await _try_fetch_pr(number)
            _append_kind("pull_request", pull_request)
        else:
            branch = await _try_fetch_branch(handle)
            _append_kind("branch", branch)

    return {
        "input": {"full_name": full_name, "handle": original_handle},
        "issue": issue,
        "pull_request": pull_request,
        "branch": branch,
        "resolved_kinds": resolved_kinds,
    }

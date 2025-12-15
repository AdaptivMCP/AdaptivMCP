from __future__ import annotations

from typing import Any, Dict

from github_mcp.config import LOG_RECORD_CAPACITY, LOG_RECORD_HANDLER


_LEVELS = {
    "CRITICAL": 50,
    "ERROR": 40,
    "WARNING": 30,
    "INFO": 20,
    "DEBUG": 10,
}


def get_recent_server_logs(limit: int = 100, min_level: str = "INFO") -> Dict[str, Any]:
    """Return recent in-memory server logs.

    Logs are collected from python logging and filtered to the github_mcp logger
    namespace.
    """

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 100
    limit_int = max(1, min(LOG_RECORD_CAPACITY, limit_int))

    min_level_upper = (min_level or "INFO").upper()
    min_level_value = _LEVELS.get(min_level_upper, _LEVELS["INFO"])

    records = getattr(LOG_RECORD_HANDLER, "records", [])
    filtered = [r for r in records if _LEVELS.get(str(r.get("level", "INFO")).upper(), 20) >= min_level_value]

    filtered = list(reversed(filtered))[:limit_int]

    return {
        "limit": limit_int,
        "capacity": LOG_RECORD_CAPACITY,
        "min_level": min_level_upper,
        "logs": filtered,
    }

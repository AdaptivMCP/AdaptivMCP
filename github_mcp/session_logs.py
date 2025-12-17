from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


DEFAULT_SESSION_LOG_DIR = "session_logs"
DEFAULT_SESSION_PREFIX = "refactor_session"
DEFAULT_TIMEZONE = "America/Toronto"


@dataclass(frozen=True)
class SessionLogContext:
    tz_name: str
    date_str: str
    rel_path: str
    abs_path: str


def _now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo is None:
        return datetime.now(timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(timezone.utc).astimezone(tz)


def resolve_session_log_path(
    repo_dir: str | os.PathLike[str],
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    session_dir: str = DEFAULT_SESSION_LOG_DIR,
    prefix: str = DEFAULT_SESSION_PREFIX,
    now: Optional[datetime] = None,
) -> SessionLogContext:
    """Return the session log path for the current date in a timezone."""

    dt = now or _now_in_tz(tz_name)
    date_str = dt.strftime("%Y-%m-%d")
    rel_path = f"{session_dir}/{prefix}_{date_str}.md"
    abs_path = str(Path(repo_dir) / rel_path)
    return SessionLogContext(
        tz_name=tz_name, date_str=date_str, rel_path=rel_path, abs_path=abs_path
    )


def ensure_session_log_file(
    repo_dir: str | os.PathLike[str],
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    session_dir: str = DEFAULT_SESSION_LOG_DIR,
    prefix: str = DEFAULT_SESSION_PREFIX,
    now: Optional[datetime] = None,
) -> SessionLogContext:
    """Create the daily session log file if it doesn't exist."""

    ctx = resolve_session_log_path(
        repo_dir,
        tz_name=tz_name,
        session_dir=session_dir,
        prefix=prefix,
        now=now,
    )
    abs_path = Path(ctx.abs_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    if not abs_path.exists():
        title = f"# Session log — {ctx.date_str}\n"
        intro = (
            "\n"
            "This file is automatically updated by the controller after each commit/push.\n"
            "It is written for end users: what changed, why it changed (when provided), what was verified, and what happens next.\n"
        )
        abs_path.write_text(title + intro + "\n", encoding="utf-8")

    return ctx


def append_session_log_entry(
    repo_dir: str | os.PathLike[str],
    entry_md: str,
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    session_dir: str = DEFAULT_SESSION_LOG_DIR,
    prefix: str = DEFAULT_SESSION_PREFIX,
    now: Optional[datetime] = None,
) -> SessionLogContext:
    ctx = ensure_session_log_file(
        repo_dir,
        tz_name=tz_name,
        session_dir=session_dir,
        prefix=prefix,
        now=now,
    )

    abs_path = Path(ctx.abs_path)
    existing = abs_path.read_text(encoding="utf-8")
    needs_nl = existing and not existing.endswith("\n")

    chunk = entry_md.strip() + "\n\n"
    abs_path.write_text(existing + ("\n" if needs_nl else "") + chunk, encoding="utf-8")
    return ctx


def format_bullets(lines: Iterable[str], *, max_items: int = 30) -> str:
    out = []
    count = 0
    for line in lines:
        if not line:
            continue
        out.append(f"- {line}")
        count += 1
        if count >= max_items:
            break
    return "\n".join(out)

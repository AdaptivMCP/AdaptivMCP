from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from github_mcp.session_logs import (
    append_session_log_entry,
    ensure_session_log_file,
    resolve_session_log_path,
)


def test_resolve_session_log_path_uses_date(tmp_path: Path):
    now = datetime(2025, 12, 17, 5, 0, 0, tzinfo=timezone.utc)
    ctx = resolve_session_log_path(tmp_path, tz_name="UTC", now=now)
    assert ctx.date_str == "2025-12-17"
    assert ctx.rel_path.endswith("refactor_session_2025-12-17.md")


def test_ensure_and_append_session_log(tmp_path: Path):
    now = datetime(2025, 12, 17, 5, 0, 0, tzinfo=timezone.utc)
    ctx = ensure_session_log_file(tmp_path, tz_name="UTC", now=now)

    p = tmp_path / ctx.rel_path
    assert p.exists()

    append_session_log_entry(tmp_path, "## Entry\nHello", tz_name="UTC", now=now)
    content = p.read_text(encoding="utf-8")

    assert "# Session log — 2025-12-17" in content
    assert "## Entry" in content
    assert "Hello" in content

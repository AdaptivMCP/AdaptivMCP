"""Helpers for write diff logging."""

from __future__ import annotations

import github_mcp.config as config
from github_mcp.diff_utils import colorize_unified_diff, diff_stats, truncate_diff


def log_write_diff(
    action: str,
    *,
    full_name: str,
    path: str,
    diff_text: str,
    detail_suffix: str = "",
) -> None:
    """Log a summary and optional diff for a write operation."""

    stats = diff_stats(diff_text)

    try:
        config.TOOLS_LOGGER.chat(
            "%s %s (+%s -%s)",
            action,
            path,
            stats.added,
            stats.removed,
            extra={
                "repo": full_name,
                "path": path,
                "event": "write_diff_summary",
                "action": action,
            },
        )

        if (
            config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL)
            and diff_text.strip()
        ):
            truncated = truncate_diff(
                diff_text,
                max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
            )
            colored = colorize_unified_diff(truncated)
            config.TOOLS_LOGGER.detailed(
                "Diff for %s%s\n%s",
                path,
                detail_suffix,
                colored,
                extra={
                    "repo": full_name,
                    "path": path,
                    "event": "write_diff",
                    "action": action,
                },
            )
    except Exception:
        config.TOOLS_LOGGER.debug(
            "Diff logging failed",
            exc_info=True,
            extra={"repo": full_name, "path": path, "event": "write_diff_error"},
        )

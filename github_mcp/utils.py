"""Utility helpers shared by GitHub MCP tools."""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Dict, Mapping


def _env_flag(name: str, default: bool = False) -> bool:
    """Return True when an environment variable is set to a truthy value."""

    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "y", "on"}


def _effective_ref_for_repo(full_name: str, ref: str | None) -> str:
    if full_name == CONTROLLER_REPO:
        if not ref or ref == "main":
            return CONTROLLER_DEFAULT_BRANCH
        return ref

    if ref:
        return ref
    repo_defaults = REPO_DEFAULTS.get(full_name)
    if repo_defaults and repo_defaults.get("default_branch"):
        return repo_defaults["default_branch"]
    return "main"


def _with_numbered_lines(text: str) -> list[Dict[str, Any]]:
    return [{"line": idx, "text": line} for idx, line in enumerate(text.splitlines(), 1)]


def _render_visible_whitespace(text: str) -> str:
    """Surface whitespace characters for assistants that hide them by default."""

    rendered_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        body = body.replace("\t", "→\t").replace(" ", "·")
        newline_marker = "⏎" if line.endswith("\n") else "␄"
        rendered_lines.append(f"{body}{newline_marker}")

    return "\n".join(rendered_lines)


def normalize_args(raw_args: Any) -> Mapping[str, Any]:
    """Normalize tool args to a JSON-friendly mapping."""

    if raw_args is None:
        return {}

    if isinstance(raw_args, Mapping):
        return dict(raw_args)

    if isinstance(raw_args, str):
        stripped = raw_args.lstrip()

        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"args must be a valid JSON object/array: {exc}"
                ) from exc

            if not isinstance(parsed, Mapping):
                raise TypeError(
                    f"args JSON must decode to an object, got {type(parsed).__name__}"
                )

            return dict(parsed)

        raise TypeError(
            "Adaptiv tools must receive args as a structured object (prefer a Python dict). "
            "If a tool needs a free-form string, place it inside the args mapping "
            "as a field instead of passing the string as the entire args payload. "
            "JSON text is supported only as a compatibility path when it decodes to an object."
        )

    raise TypeError(f"Unsupported args type: {type(raw_args).__name__}")


def _decode_zipped_job_logs(zip_bytes: bytes) -> str:
    """Extract and concatenate text files from a zipped job log archive."""

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
            parts: list[str] = []
            for name in sorted(
                entry
                for entry in zip_file.namelist()
                if not entry.endswith("/")
            ):
                with zip_file.open(name) as handle:
                    content = handle.read().decode("utf-8", errors="replace")
                parts.append(f"[{name}]\n{content}".rstrip())
            return "\n\n".join(parts)
    except Exception:
        return ""


# Lazy import to avoid cycles when config loads environment defaults.
import os  # noqa: E402  pylint: disable=wrong-import-position
from . import config  # noqa: E402  pylint: disable=wrong-import-position

REPO_DEFAULTS: Dict[str, Dict[str, str]] = json.loads(
    os.environ.get("GITHUB_REPO_DEFAULTS", "{}")
)
CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get(
    "GITHUB_MCP_CONTROLLER_BRANCH", "main"
)

__all__ = [
    "REPO_DEFAULTS",
    "_decode_zipped_job_logs",
    "_effective_ref_for_repo",
    "_env_flag",
    "_render_visible_whitespace",
    "_with_numbered_lines",
    "normalize_args",
]

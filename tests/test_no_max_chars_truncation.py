from __future__ import annotations

import re

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# Guardrail: max-character truncation controls were removed and must not return.
FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bGITHUB_MCP_RESPONSE_MAX_(JSON|TEXT)_CHARS\b"),
    re.compile(r"\bCHATGPT_RESPONSE_MAX_(JSON|TEXT)_CHARS\b"),
    re.compile(r"\bGITHUB_MCP_MAX_FILE_CONTENT_BYTES\b"),
    re.compile(r"\bGITHUB_MCP_MAX_FILE_TEXT_CHARS\b"),
    re.compile(r"\bGITHUB_MCP_MAX_FETCH_URL_BYTES\b"),
    re.compile(r"\bGITHUB_MCP_MAX_FETCH_URL_TEXT_CHARS\b"),
    re.compile(r"\bdef\s+_truncate_string\b"),
    re.compile(r"\bdef\s+_safe_json_dumps\b"),
    re.compile(r"\bjson_truncated\b"),
]


def _iter_source_files() -> list[Path]:
    ex_dirs = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in ex_dirs for part in p.parts):
            continue
        if p.suffix.lower() in {".py", ".md", ".txt", ".toml", ".yml", ".yaml"} or p.name.endswith(
            ".env.example"
        ):
            out.append(p)
    return out


def test_no_max_chars_truncation_knobs_or_code_paths_exist() -> None:
    offenders: list[str] = []
    for path in _iter_source_files():
        # The test itself intentionally references the forbidden strings.
        if path.name == "test_no_max_chars_truncation.py":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in FORBIDDEN_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            excerpt_start = max(0, m.start() - 60)
            excerpt_end = min(len(content), m.end() + 60)
            excerpt = content[excerpt_start:excerpt_end].replace("\n", "\\n")
            offenders.append(
                f"{path.relative_to(REPO_ROOT)} matched /{pat.pattern}/ near: {excerpt}"
            )

    assert not offenders, "Forbidden patterns found:\n" + "\n".join(offenders)


def test_docs_do_not_mention_removed_max_chars_controls() -> None:
    usage = REPO_ROOT / "docs" / "usage.md"
    if not usage.exists():
        pytest.skip("docs/usage.md is missing")
    text = usage.read_text(encoding="utf-8")
    assert "GITHUB_MCP_RESPONSE_MAX_JSON_CHARS" not in text
    assert "GITHUB_MCP_RESPONSE_MAX_TEXT_CHARS" not in text

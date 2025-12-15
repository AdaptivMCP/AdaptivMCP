#!/usr/bin/env python3
"""Fail CI if docs drift away from the repo's edit policy.

This repo intentionally prefers full-file replacement edits over diff/patch editing tools.
Docs (especially assistant/controller prompts) should not instruct assistants to use
patch/diff editing tools as the default.

This script is intentionally simple and dependency-free.
"""

from __future__ import annotations

import pathlib
import re

DOCS_DIRS = [pathlib.Path("docs"), pathlib.Path("README.md")]

# Phrases we want to block because they steer assistants toward diff/patch edits.
# Keep these narrow to avoid false positives.
BLOCK_PATTERNS = [
    re.compile(r"\bprefer\s+diff\b", re.IGNORECASE),
    re.compile(r"\bdiff-based\b", re.IGNORECASE),
    re.compile(r"\bpatch\s+tools\b", re.IGNORECASE),
    re.compile(r"\bapply\s+patch\b", re.IGNORECASE),
]

# Phrases that are allowed even though they contain 'diff'/'patch' substrings.
ALLOW_PATTERNS = [
    re.compile(r"git\s+commits?\s+already\s+provide\s+diffs?", re.IGNORECASE),
    re.compile(r"avoid\s+diff/patch", re.IGNORECASE),
]


def iter_doc_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for p in DOCS_DIRS:
        if p.is_file():
            files.append(p)
            continue
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
    return files


def main() -> int:
    offenders: list[str] = []

    for path in iter_doc_files():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        for pat in BLOCK_PATTERNS:
            for m in pat.finditer(text):
                window = text[max(0, m.start() - 80) : min(len(text), m.end() + 80)]
                if any(ap.search(window) for ap in ALLOW_PATTERNS):
                    continue
                offenders.append(f"{path}: contains policy-violating phrase near: {window!r}")

    if offenders:
        print("Doc policy check failed. Remove diff/patch-default guidance from docs.")
        for line in offenders:
            print("-", line)
        return 1

    print("Doc policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

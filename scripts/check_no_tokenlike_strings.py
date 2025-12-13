#!/usr/bin/env python3
"""Fail CI if token-like secrets appear in tracked text files.

Goal: prevent assistants from copying token-shaped strings (e.g., PAT formats) into docs/tests/examples,
which can trigger upstream OpenAI blocks or accidental leakage.

Design constraints:
- Never print the matched token-like text.
- Print file:line plus a rule id.
- Allow explicit opt-out per-line with: tokenlike-allow

Usage:
  python scripts/check_no_tokenlike_strings.py

Exit code:
  0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    description: str


RULES: list[Rule] = [
    Rule(
        rule_id="TOKEN_GHP",
        pattern=re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        description="GitHub classic token format detected",
    ),
    Rule(
        rule_id="TOKEN_GITHUB_PAT",
        pattern=re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        description="GitHub fine-grained PAT format detected",
    ),
    Rule(
        rule_id="TOKEN_X_ACCESS_TOKEN_URL",
        pattern=re.compile(r"https://x-access-token:[^@\s]+@github\.com/"),
        description="x-access-token URL embedding detected",
    ),
    Rule(
        rule_id="TOKEN_X_ACCESS_TOKEN_INLINE",
        pattern=re.compile(r"x-access-token:[^@\s]+@github\.com"),
        description="x-access-token inline embedding detected",
    ),
    Rule(
        rule_id="ENV_ASSIGNMENT_TOKEN",
        # catches e.g. GITHUB_PAT=ghp_... or GITHUB_TOKEN=... (but not placeholders)
        pattern=re.compile(
            r"\b(GITHUB_PAT|GITHUB_TOKEN)=(?!<YOUR_GITHUB_TOKEN>|<REDACTED>|\$\{?\w+\}?)[^\s#]+"
        ),
        description="Token-like env var assignment detected",
    ),
]


TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".py",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".js",
    ".ts",
}


def _git_tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    files: list[Path] = []
    for line in out.splitlines():
        p = Path(line.strip())
        if not p.name:
            continue
        if p.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        # Skip vendored/binary-ish directories if they appear in repo
        if any(part in {".git", "assets", "sandbox"} for part in p.parts):
            continue
        files.append(p)
    return files


def _iter_violations(path: Path, rules: Iterable[Rule]):
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return

    for i, line in enumerate(content.splitlines(), start=1):
        if "tokenlike-allow" in line:
            continue
        for rule in rules:
            if rule.pattern.search(line):
                yield (i, rule.rule_id)


def main() -> int:
    violations: list[str] = []
    for path in _git_tracked_files():
        for line_no, rule_id in _iter_violations(path, RULES):
            violations.append(f"{path}:{line_no}: {rule_id}")

    if violations:
        print(
            "Token-like string violations detected. Replace with placeholders like <YOUR_GITHUB_TOKEN> or <REDACTED>."
        )
        for v in violations:
            print(v)
        return 1

    print("No token-like strings detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fingerprint requirements together with their local includes and constraints."""

from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path


def requirements_hash(requirements_path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        payload = resolved.read_bytes()
        digest.update(payload)
        text = payload.decode("utf-8-sig").replace("\\\n", "")
        for line in text.splitlines():
            if not line.lstrip().startswith(
                ("-r", "-c", "--requirement", "--constraint")
            ):
                continue
            parts = shlex.split(line, comments=True)
            if not parts:
                continue
            option = parts[0]
            include = None
            if option in {"-r", "--requirement", "-c", "--constraint"}:
                if len(parts) > 1:
                    include = parts[1]
            elif option.startswith(("--requirement=", "--constraint=")):
                include = option.split("=", 1)[1]
            elif option.startswith(("-r", "-c")) and len(option) > 2:
                include = option[2:]
            if include and "://" not in include:
                digest.update(b"\0")
                visit(resolved.parent / os.path.expandvars(include))

    visit(Path(requirements_path))
    return digest.hexdigest()

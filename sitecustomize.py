"""Compatibility helpers for older Python runtimes.

This project targets environments that may still be on Python 3.10, which
doesn't expose `typing.NotRequired` / `typing.Required`. Provide a small
shim so tests (and runtime code) can import these symbols without depending
on Python 3.11+.
"""

from __future__ import annotations

import typing

try:
    from typing_extensions import NotRequired, Required
except ImportError:  # pragma: no cover - typing_extensions missing
    NotRequired = None  # type: ignore[assignment]
    Required = None  # type: ignore[assignment]

if NotRequired is not None and not hasattr(typing, "NotRequired"):
    typing.NotRequired = NotRequired  # type: ignore[attr-defined]

if Required is not None and not hasattr(typing, "Required"):
    typing.Required = Required  # type: ignore[attr-defined]

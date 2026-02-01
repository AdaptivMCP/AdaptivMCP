from __future__ import annotations

import sys
import typing
import importlib.util
import asyncio
import inspect
from datetime import timezone
import datetime
from pathlib import Path

import pytest

try:
    from typing_extensions import NotRequired, Required
except ImportError:  # pragma: no cover - typing_extensions missing
    NotRequired = None  # type: ignore[assignment]
    Required = None  # type: ignore[assignment]

if NotRequired is not None and not hasattr(typing, "NotRequired"):
    typing.NotRequired = NotRequired  # type: ignore[attr-defined]

if Required is not None and not hasattr(typing, "Required"):
    typing.Required = Required  # type: ignore[attr-defined]

if not hasattr(datetime, "UTC"):
    datetime.UTC = timezone.utc  # type: ignore[attr-defined]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HAS_PYTEST_ASYNCIO = importlib.util.find_spec("pytest_asyncio") is not None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio: mark async tests (handled by pytest-asyncio or anyio fallback).",
    )
    if not HAS_PYTEST_ASYNCIO:
        config.addinivalue_line(
            "markers",
            "anyio: mark tests for anyio backend execution.",
        )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if HAS_PYTEST_ASYNCIO:
        return
    for item in items:
        if "asyncio" in item.keywords and "anyio" not in item.keywords:
            item.add_marker(pytest.mark.anyio)


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if HAS_PYTEST_ASYNCIO:
        return None
    if "asyncio" not in pyfuncitem.keywords:
        return None
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    fixture_kwargs = {
        name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(pyfuncitem.obj(**fixture_kwargs))
    return True

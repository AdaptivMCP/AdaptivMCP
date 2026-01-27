from __future__ import annotations

import builtins
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest


def _load_sitecustomize(
    *,
    monkeypatch: pytest.MonkeyPatch,
    typing_mod: types.ModuleType,
    typing_extensions_mod: types.ModuleType | None,
    force_typing_extensions_import_error: bool = False,
) -> None:
    """Load sitecustomize.py under an isolated module name.

    Many Python environments auto-import `sitecustomize` at interpreter start,
    so we avoid importing it by that canonical name.
    """

    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "sitecustomize.py"

    # Ensure sitecustomize imports our controlled typing modules.
    monkeypatch.setitem(sys.modules, "typing", typing_mod)

    if typing_extensions_mod is None:
        monkeypatch.delitem(sys.modules, "typing_extensions", raising=False)
    else:
        monkeypatch.setitem(sys.modules, "typing_extensions", typing_extensions_mod)

    if force_typing_extensions_import_error:
        real_import = builtins.__import__

        def fake_import(
            name: str,
            globals: Any | None = None,
            locals: Any | None = None,
            fromlist: tuple[str, ...] | list[str] = (),
            level: int = 0,
        ) -> Any:
            if name == "typing_extensions":
                raise ImportError("typing_extensions intentionally unavailable")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

    module_name = f"_sitecustomize_under_test_{id(typing_mod)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None

    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, mod)
    spec.loader.exec_module(mod)


def test_sitecustomize_injects_notrequired_and_required(monkeypatch: pytest.MonkeyPatch) -> None:
    typing_mod = types.ModuleType("typing")

    typing_extensions_mod = types.ModuleType("typing_extensions")
    not_required_sentinel = object()
    required_sentinel = object()
    typing_extensions_mod.NotRequired = not_required_sentinel  # type: ignore[attr-defined]
    typing_extensions_mod.Required = required_sentinel  # type: ignore[attr-defined]

    _load_sitecustomize(
        monkeypatch=monkeypatch,
        typing_mod=typing_mod,
        typing_extensions_mod=typing_extensions_mod,
    )

    assert getattr(typing_mod, "NotRequired") is not_required_sentinel
    assert getattr(typing_mod, "Required") is required_sentinel


def test_sitecustomize_does_not_override_existing_typing_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typing_mod = types.ModuleType("typing")
    typing_mod.NotRequired = "already"  # type: ignore[attr-defined]
    typing_mod.Required = "present"  # type: ignore[attr-defined]

    typing_extensions_mod = types.ModuleType("typing_extensions")
    typing_extensions_mod.NotRequired = object()  # type: ignore[attr-defined]
    typing_extensions_mod.Required = object()  # type: ignore[attr-defined]

    _load_sitecustomize(
        monkeypatch=monkeypatch,
        typing_mod=typing_mod,
        typing_extensions_mod=typing_extensions_mod,
    )

    assert typing_mod.NotRequired == "already"  # type: ignore[attr-defined]
    assert typing_mod.Required == "present"  # type: ignore[attr-defined]


def test_sitecustomize_handles_missing_typing_extensions(monkeypatch: pytest.MonkeyPatch) -> None:
    typing_mod = types.ModuleType("typing")

    _load_sitecustomize(
        monkeypatch=monkeypatch,
        typing_mod=typing_mod,
        typing_extensions_mod=None,
        force_typing_extensions_import_error=True,
    )

    assert not hasattr(typing_mod, "NotRequired")
    assert not hasattr(typing_mod, "Required")

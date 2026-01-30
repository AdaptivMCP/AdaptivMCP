from __future__ import annotations

from github_mcp.main_tools.handles import (
    ParsedHandle,
    _extract_trailing_int,
    coerce_issue_or_pr_number,
    parse_handle,
)

import pytest


def test_extract_trailing_int_basic() -> None:
    assert _extract_trailing_int("#123") == 123
    assert _extract_trailing_int("123") == 123
    assert _extract_trailing_int("/issues/456") == 456
    assert _extract_trailing_int("abc") is None
    assert _extract_trailing_int("") is None


def test_extract_trailing_int_non_digit_suffix() -> None:
    assert _extract_trailing_int("123abc") is None
    assert _extract_trailing_int("/issues/123/") is None
    assert _extract_trailing_int("-123") == 123  # scans digits only


def test_extract_trailing_int_int_conversion_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the int(...) conversion to raise to hit the defensive except branch.
    import github_mcp.main_tools.handles as handles_mod

    real_int = int

    def _boom(value, *args, **kwargs):  # type: ignore[no-untyped-def]
        if value == "123":
            raise ValueError("bad int")
        return real_int(value, *args, **kwargs)

    # Patch the module global name `int` (not builtins) so we don't break pytest internals.
    # Use raising=False because handles.py normally resolves `int` from builtins.
    monkeypatch.setattr(handles_mod, "int", _boom, raising=False)
    assert _extract_trailing_int("123") is None


def test_parse_handle_empty() -> None:
    assert parse_handle(None) == ParsedHandle(raw="", number=None, canonical="")
    assert parse_handle("   ") == ParsedHandle(raw="", number=None, canonical="")


def test_parse_handle_hash_prefix() -> None:
    assert parse_handle("#123").number == 123
    assert parse_handle("#  123").canonical == "#123"
    # non-digit after '#'
    assert parse_handle("#abc").number is None


def test_parse_handle_plain_digits() -> None:
    assert parse_handle("123") == ParsedHandle(raw="123", number=123, canonical="#123")


def test_parse_handle_urls_and_freeform() -> None:
    assert (
        parse_handle("https://github.com/o/r/issues/99").canonical == "#99"
    )
    assert parse_handle("issue #77").canonical == "#77"
    assert parse_handle("https://github.com/o/r/pull/55").number == 55
    assert parse_handle("no number here").canonical == "no number here"


def test_coerce_issue_or_pr_number() -> None:
    assert coerce_issue_or_pr_number("#1") == 1
    assert coerce_issue_or_pr_number("https://x/y/2") == 2
    assert coerce_issue_or_pr_number("abc") is None


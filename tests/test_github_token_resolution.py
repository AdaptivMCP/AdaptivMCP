from __future__ import annotations

import pytest

from github_mcp.config import GITHUB_TOKEN_ENV_VARS
from github_mcp.exceptions import GitHubAuthError
from github_mcp.http_clients import _get_github_token, _get_optional_github_token


def _clear_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in GITHUB_TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_github_token_prefers_first_non_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_token_env(monkeypatch)

    monkeypatch.setenv("GITHUB_PAT", "   ")
    monkeypatch.setenv("GITHUB_TOKEN", "real-token")

    assert _get_optional_github_token() == "real-token"
    assert _get_github_token() == "real-token"


def test_github_token_errors_when_only_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_token_env(monkeypatch)

    monkeypatch.setenv("GITHUB_PAT", "")

    assert _get_optional_github_token() is None
    with pytest.raises(GitHubAuthError, match="GITHUB_PAT is empty"):
        _get_github_token()

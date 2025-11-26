import importlib

import pytest


def _reload_main_with_token(monkeypatch: pytest.MonkeyPatch, value: str | None):
    if value is None:
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_PAT", value)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    import main as main_module

    return importlib.reload(main_module)


def test_get_github_token_strips_whitespace(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main_with_token(monkeypatch, "  ghp_exampletoken  \n")
    assert module._get_github_token() == "ghp_exampletoken"


@pytest.mark.parametrize("value", ["", " ", "\t\n  \t"])
def test_get_github_token_rejects_empty_or_space_only(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    module = _reload_main_with_token(monkeypatch, value)

    with pytest.raises(module.GitHubAuthError):
        module._get_github_token()

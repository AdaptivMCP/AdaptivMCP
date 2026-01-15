import os

import pytest


def test_normalize_repo_path_for_repo_strips_github_blob_url():
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    url = "https://github.com/octo-org/octo-repo/blob/main/docs/readme.md"
    assert utils._normalize_repo_path_for_repo(full_name, url) == "docs/readme.md"


def test_normalize_repo_path_for_repo_strips_github_tree_url():
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    url = "github.com/octo-org/octo-repo/tree/main/docs"
    assert utils._normalize_repo_path_for_repo(full_name, url) == "docs"


def test_normalize_repo_path_for_repo_strips_raw_github_url():
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    url = "https://raw.githubusercontent.com/octo-org/octo-repo/main/docs/readme.md"
    assert utils._normalize_repo_path_for_repo(full_name, url) == "docs/readme.md"


@pytest.mark.parametrize("value", ["/", "", ".", "./", "https://github.com/octo-org/octo-repo"])
def test_normalize_repo_path_for_repo_repo_root_like_values_strict(value, monkeypatch):
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    monkeypatch.setenv("GITHUB_MCP_STRICT_CONTRACTS", "1")
    with pytest.raises(Exception) as excinfo:
        utils._normalize_repo_path_for_repo(full_name, value)

    assert "expected a repository-relative file path" in str(excinfo.value)


@pytest.mark.parametrize("value", ["/", "", ".", "./", "https://github.com/octo-org/octo-repo"])
def test_normalize_repo_path_for_repo_repo_root_like_values_permissive(value, monkeypatch):
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    monkeypatch.delenv("GITHUB_MCP_STRICT_CONTRACTS", raising=False)
    assert utils._normalize_repo_path_for_repo(full_name, value) == ""

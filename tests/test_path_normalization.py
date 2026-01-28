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


@pytest.mark.parametrize(
    "value",
    ["/", "", ".", "./", "https://github.com/octo-org/octo-repo"],
)
def test_normalize_repo_path_for_repo_repo_root_like_values_are_permissive(
    value, monkeypatch
):
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    # Legacy env var should not change behavior; normalization is always permissive.
    monkeypatch.setenv("ADAPTIV_MCP_STRICT_CONTRACTS", "1")
    assert utils._normalize_repo_path_for_repo(full_name, value) == ""


@pytest.mark.parametrize(
    "value",
    ["/", "", ".", "./", "https://github.com/octo-org/octo-repo"],
)
def test_normalize_repo_path_for_repo_repo_root_like_values_permissive(
    value, monkeypatch
):
    from github_mcp import utils

    full_name = "octo-org/octo-repo"
    monkeypatch.delenv("ADAPTIV_MCP_STRICT_CONTRACTS", raising=False)
    assert utils._normalize_repo_path_for_repo(full_name, value) == ""


def test_normalize_repo_path_rejects_parent_traversal():
    from github_mcp import utils
    assert utils._normalize_repo_path("../secrets.txt") == "../secrets.txt"
    assert utils._normalize_repo_path("docs/../secrets.txt") == "docs/../secrets.txt"

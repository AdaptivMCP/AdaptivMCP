import pytest


def test_sanitize_workspace_ref_allows_branch_paths():
    from github_mcp import workspace

    assert workspace._sanitize_workspace_ref("feature/new-ui") == "feature/new-ui"


def test_sanitize_workspace_ref_rejects_parent_traversal():
    from github_mcp import workspace
    from github_mcp.exceptions import GitHubAPIError

    with pytest.raises(GitHubAPIError):
        workspace._sanitize_workspace_ref("../escape")

    with pytest.raises(GitHubAPIError):
        workspace._sanitize_workspace_ref("feature/../escape")


def test_sanitize_workspace_ref_rejects_absolute_paths_and_colons():
    from github_mcp import workspace
    from github_mcp.exceptions import GitHubAPIError

    with pytest.raises(GitHubAPIError, match="absolute path"):
        workspace._sanitize_workspace_ref("/etc/passwd")

    with pytest.raises(GitHubAPIError, match=":"):
        workspace._sanitize_workspace_ref("feature:bad")


def test_sanitize_workspace_ref_defaults_to_main_for_empty_like_inputs():
    from github_mcp import workspace

    assert workspace._sanitize_workspace_ref("") == "main"
    assert workspace._sanitize_workspace_ref("   ") == "main"
    assert workspace._sanitize_workspace_ref("./") == "main"

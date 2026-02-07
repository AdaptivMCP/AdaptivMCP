import pytest


def test_is_git_rate_limit_error_matches_expected_markers():
    from github_mcp import workspace

    assert workspace._is_git_rate_limit_error("fatal: rate limit exceeded")
    assert workspace._is_git_rate_limit_error("Secondary rate limit")
    assert workspace._is_git_rate_limit_error("ABUSE DETECTION mechanism")
    assert not workspace._is_git_rate_limit_error("unrelated error")


def test_append_git_config_env_increments_count_and_sets_key_value():
    from github_mcp import workspace

    env: dict[str, str] = {}
    workspace._append_git_config_env(
        env, "http.extraHeader", "Authorization: Basic abc"
    )

    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic abc"

    # Second append should increment and use the next index.
    workspace._append_git_config_env(env, "core.askpass", "")
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_1"] == "core.askpass"
    assert env["GIT_CONFIG_VALUE_1"] == ""


def test_git_env_has_auth_header_detects_both_header_styles():
    from github_mcp import workspace

    env = {"GIT_TERMINAL_PROMPT": "0"}
    assert not workspace._git_env_has_auth_header(env)

    env["GIT_HTTP_EXTRAHEADER"] = "Authorization: Basic abc"
    assert workspace._git_env_has_auth_header(env)

    # Config-env form.
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": "Authorization: Basic abc",
    }
    assert workspace._git_env_has_auth_header(env)


def test_raise_git_auth_error_raises_for_auth_like_messages():
    from github_mcp import workspace
    from github_mcp.exceptions import GitHubAuthError

    with pytest.raises(GitHubAuthError):
        workspace._raise_git_auth_error(
            "clone",
            "Authentication failed for 'https://github.com/x/y'\nSome extra detail",
        )

    # Non-auth errors should not raise.
    workspace._raise_git_auth_error("clone", "fatal: not a git repository")


def test_git_auth_env_without_token_returns_prompt_setting(monkeypatch):
    from github_mcp import workspace
    from github_mcp.exceptions import GitHubAuthError

    def raise_auth_error() -> str:
        raise GitHubAuthError("missing token")

    monkeypatch.setattr(workspace, "_get_github_token", raise_auth_error)

    env = workspace._git_auth_env()
    assert env == {"GIT_TERMINAL_PROMPT": "0"}


def test_git_auth_env_sets_http_header_and_config(monkeypatch):
    from github_mcp import workspace

    monkeypatch.setattr(workspace, "_get_github_token", lambda: "secret-token")

    env = workspace._git_auth_env()

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_HTTP_EXTRAHEADER"].startswith("Authorization: Basic ")
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == env["GIT_HTTP_EXTRAHEADER"]



def _assert_step_meta(step: dict) -> None:
    assert step.get("actor") == "assistant"
    assert step.get("user_can_invoke_tools") is False


def test_structured_error_includes_actor_and_step_metadata_for_validation():
    from github_mcp import server

    payload = server._structured_tool_error(ValueError("bad"), context="create_branch")

    err = payload["error"]
    assert err["actor"] == "assistant"
    assert err["user_can_invoke_tools"] is False
    assert err["origin"] == "adaptiv_controller"
    assert err["category"] == "validation"

    steps = err["next_steps"]
    assert steps
    for step in steps:
        _assert_step_meta(step)


def test_openai_block_error_guidance_points_to_workspace_fallback():
    from github_mcp import server

    msg = "blocked by OpenAI because we couldn't determine the safety status of the request"
    payload = server._structured_tool_error(RuntimeError(msg), context="create_branch")

    err = payload["error"]
    assert err["origin"] == "openai_platform"
    assert err["category"] == "openai_block"
    assert err["actor"] == "assistant"
    assert err["user_can_invoke_tools"] is False

    steps = err["next_steps"]
    assert steps[0]["kind"] == "openai"
    _assert_step_meta(steps[0])
    assert "Do not ask the user" in steps[0].get("what_to_do", "")

    # Workspace fallback for branch creation.
    assert any(
        s.get("kind") == "workspace_fallback" and s.get("tool") == "workspace_create_branch"
        for s in steps
    )


def test_pr_hint_step_also_includes_actor_metadata():
    from github_mcp import server

    payload = server._structured_tool_error(ValueError("bad"), context="create_pull_request")
    steps = payload["error"]["next_steps"]

    # Should include a PR-specific hint step.
    pr_hints = [s for s in steps if s.get("kind") == "hint" and "PR creation" in s.get("action", "")]
    assert pr_hints
    for step in pr_hints:
        _assert_step_meta(step)

from main import (
    CONTROLLER_CONTRACT_VERSION,
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    WRITE_ALLOWED,
    controller_contract,
)


def test_controller_contract_full_structure():
    payload = controller_contract(compact=False)

    assert payload["version"] == CONTROLLER_CONTRACT_VERSION
    assert payload["controller"]["repo"] == CONTROLLER_REPO
    assert payload["controller"]["default_branch"] == CONTROLLER_DEFAULT_BRANCH
    assert payload["controller"]["write_allowed_default"] == WRITE_ALLOWED

    expectations = payload["expectations"]
    for role in ("assistant", "controller_prompt", "server"):
        assert role in expectations
        assert expectations[role]
        assert all(isinstance(item, str) for item in expectations[role])

    assert any("branch" in item.lower() for item in expectations["assistant"])
    assert any("write" in item.lower() for item in expectations["assistant"])
    assert any("large" in item.lower() for item in expectations["assistant"])

    tooling = payload["tooling"]
    assert set(tooling["discovery"]) >= {"get_server_config", "list_write_tools", "validate_environment"}
    assert {"run_command", "run_tests", "commit_workspace"} <= set(
        tooling["execution"]
    )
    assert {
        "get_file_slice",
        "build_section_based_diff",
        "build_unified_diff_from_strings",
        "validate_json_string",
    } <= set(tooling["large_files"])
    assert {"create_issue", "update_issue", "comment_on_issue"} <= set(
        tooling["issues"]
    )
    assert "authorize_write_actions" in tooling["safety"]


def test_controller_contract_compact_mode():
    payload = controller_contract()

    assert payload["version"] == CONTROLLER_CONTRACT_VERSION
    assert payload["controller"]["repo"] == CONTROLLER_REPO
    assert payload["controller"]["write_allowed_default"] == WRITE_ALLOWED
    assert payload.get("compact") is True

    expectations = payload["expectations"]
    assert expectations["assistant_count"] > 0
    assert expectations["controller_prompt_count"] > 0
    assert expectations["server_count"] > 0
    assert "note" in expectations

    prompts = payload["prompts"]
    assert prompts["controller_prompt_count"] > 0
    assert prompts["server_count"] > 0

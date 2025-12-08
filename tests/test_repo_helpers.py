import json

import pytest

import main


def test_validate_json_string_valid() -> None:
    payload = {"a": 1, "b": ["x", "y"]}
    raw = json.dumps(payload)

    result = main.validate_json_string(raw)

    assert result["valid"] is True
    assert result["parsed"] == payload
    assert result["parsed_type"] == "dict"

    normalized = result["normalized"]
    assert isinstance(normalized, str)
    # Normalized JSON should parse back to the same structure.
    assert json.loads(normalized) == payload
    assert "normalized_pretty" in result


def test_validate_json_string_invalid() -> None:
    # Trailing comma makes this invalid JSON.
    raw = '{"a": 1, }'

    result = main.validate_json_string(raw)

    assert result["valid"] is False
    assert "error" in result
    assert "position" in result
    assert "snippet" in result
    assert "line_snippet" in result
    assert "pointer" in result
    # Invalid payloads should not expose a normalized value.
    assert "normalized" not in result


@pytest.mark.asyncio
async def test_get_repo_defaults_uses_github_default_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_github_request(method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "/repos/owner/repo"
        return {"json": {"default_branch": "dev"}}

    monkeypatch.setattr(main, "_github_request", fake_github_request)

    result = await main.get_repo_defaults("owner/repo")

    assert result["defaults"]["full_name"] == "owner/repo"
    assert result["defaults"]["default_branch"] == "dev"


@pytest.mark.asyncio
async def test_get_repo_defaults_falls_back_to_controller_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_github_request(method: str, path: str, **kwargs):
        # Simulate a response without a default_branch field.
        return {"json": {}}

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "CONTROLLER_DEFAULT_BRANCH", "fallback-branch")

    result = await main.get_repo_defaults("owner/repo")

    assert result["defaults"]["full_name"] == "owner/repo"
    assert result["defaults"]["default_branch"] == "fallback-branch"

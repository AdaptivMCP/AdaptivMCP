import asyncio
import tempfile

import pytest

from github_mcp.exceptions import GitHubAPIError
from github_mcp.mcp_server.error_handling import _structured_tool_error
from github_mcp.workspace import _apply_patch_to_repo


def _err_category(payload: dict) -> str:
    detail = payload.get("error_detail") or {}
    return str(detail.get("category") or "")


def _err_code(payload: dict) -> str | None:
    detail = payload.get("error_detail") or {}
    return detail.get("code")


def _err_details(payload: dict) -> dict:
    detail = payload.get("error_detail") or {}
    return dict(detail.get("details") or {})


@pytest.mark.parametrize(
    "message, expected_category, expected_code",
    [
        ("Malformed patch: no diffs found", "validation", "PATCH_MALFORMED"),
        ("Patch missing Begin Patch header", "validation", "PATCH_MALFORMED"),
        ("Unexpected patch content", "validation", "PATCH_MALFORMED"),
        ("File does not exist: foo.txt", "not_found", "FILE_NOT_FOUND"),
        ("Patch does not apply to foo.txt", "conflict", "PATCH_DOES_NOT_APPLY"),
        ("path must be repository-relative", "validation", "PATH_INVALID"),
    ],
)
def test_github_api_error_message_inference(
    message: str, expected_category: str, expected_code: str
) -> None:
    exc = GitHubAPIError(message)
    payload = _structured_tool_error(exc, context="unit:test")
    assert _err_category(payload) == expected_category
    assert _err_code(payload) == expected_code


def test_github_api_error_explicit_category_is_preserved() -> None:
    exc = GitHubAPIError("Patch does not apply to foo.txt")
    exc.category = "conflict"
    exc.code = "PATCH_DOES_NOT_APPLY"
    payload = _structured_tool_error(exc, context="unit:test")
    assert _err_category(payload) == "conflict"
    assert _err_code(payload) == "PATCH_DOES_NOT_APPLY"


def test_python_file_not_found_error_is_llm_friendly_not_found() -> None:
    exc = FileNotFoundError(2, "No such file or directory", "missing.txt")
    payload = _structured_tool_error(exc, context="unit:test")

    assert _err_category(payload) == "not_found"
    assert _err_code(payload) == "FILE_NOT_FOUND"

    details = _err_details(payload)
    assert details.get("missing_path") == "missing.txt"
    assert details.get("errno") == 2


def test_apply_patch_empty_patch_is_validation_with_code() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as repo_dir:
            with pytest.raises(GitHubAPIError) as err:
                await _apply_patch_to_repo(repo_dir, "")
            exc = err.value
            assert getattr(exc, "category", None) == "validation"
            assert getattr(exc, "code", None) == "PATCH_EMPTY"

    asyncio.run(_run())

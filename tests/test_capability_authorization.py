from __future__ import annotations

import asyncio

import pytest

from github_mcp.mcp_server.context import (
    REQUEST_CAPABILITIES,
    get_request_capabilities,
    set_request_capabilities,
)
from github_mcp.mcp_server.decorators import (
    _default_capabilities,
    _enforce_capabilities,
)
from github_mcp.exceptions import WriteApprovalRequiredError


def test_capabilities_default_to_empty():
    assert get_request_capabilities() == frozenset()


def test_capability_set_is_request_scoped():
    token = REQUEST_CAPABILITIES.set(frozenset({"git.push"}))
    try:
        assert get_request_capabilities() == frozenset({"git.push"})
    finally:
        REQUEST_CAPABILITIES.reset(token)

    assert get_request_capabilities() == frozenset()


def test_set_request_capabilities_normalizes_values():
    assert set_request_capabilities([" git.push ", "", "workspace.write"]) == frozenset(
        {"git.push", "workspace.write"}
    )


def test_missing_capability_is_denied():
    with pytest.raises(WriteApprovalRequiredError) as exc:
        _enforce_capabilities(
            "git_push",
            write_action=True,
            required_capabilities=frozenset({"git.push"}),
        )

    assert exc.value.missing_capabilities == ["git.push"]


def test_granted_capability_allows_operation():
    token = REQUEST_CAPABILITIES.set(frozenset({"git.push"}))
    try:
        _enforce_capabilities(
            "git_push",
            write_action=True,
            required_capabilities=frozenset({"git.push"}),
        )
    finally:
        REQUEST_CAPABILITIES.reset(token)


def test_capabilities_are_not_satisfied_by_a_different_capability():
    token = REQUEST_CAPABILITIES.set(frozenset({"workspace.write"}))
    try:
        with pytest.raises(WriteApprovalRequiredError):
            _enforce_capabilities(
                "git_push",
                write_action=True,
                required_capabilities=frozenset({"git.push"}),
            )
    finally:
        REQUEST_CAPABILITIES.reset(token)


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("workspace_create_branch", "workspace.write"),
        ("workspace_git_push", "git.push"),
        ("commit_workspace", "git.commit"),
        ("merge_pull_request", "github.merge"),
        ("create_pull_request", "github.write"),
        ("render_deploy_service", "render.write"),
    ],
)
def test_default_capability_mapping(tool_name, expected):
    assert _default_capabilities(tool_name, True) == frozenset({expected})


def test_read_tools_require_no_capability():
    assert _default_capabilities("workspace_git_status", False) == frozenset()


def test_concurrent_requests_do_not_share_capabilities():
    async def worker(capability: str) -> frozenset[str]:
        token = REQUEST_CAPABILITIES.set(frozenset({capability}))
        try:
            await asyncio.sleep(0)
            return get_request_capabilities()
        finally:
            REQUEST_CAPABILITIES.reset(token)

    async def run():
        return await asyncio.gather(
            worker("git.push"),
            worker("github.write"),
        )

    first, second = asyncio.run(run())
    assert first == frozenset({"git.push"})
    assert second == frozenset({"github.write"})


def test_command_resolver_is_rejected_as_an_authorization_bypass() -> None:
    from github_mcp.mcp_server import decorators

    with pytest.raises(TypeError, match="write_action_resolver is no longer supported"):
        decorators.mcp_tool(
            write_action=False,
            write_action_resolver=lambda _args: True,
        )

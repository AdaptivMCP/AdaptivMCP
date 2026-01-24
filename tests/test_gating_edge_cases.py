from __future__ import annotations

from collections.abc import Callable
from typing import Any


def test_infer_write_action_from_shell_chained_commands() -> None:
    """Ensure common shell separators are handled conservatively but correctly."""

    from github_mcp.command_classification import infer_write_action_from_shell

    # Pure read chains.
    assert infer_write_action_from_shell("ls && pwd") is False
    assert infer_write_action_from_shell("git status ; rg -n foo .") is False
    assert infer_write_action_from_shell("true || ls") is False

    # Mixed chains should be classified as write.
    assert infer_write_action_from_shell("ls && rm -f x") is True
    assert infer_write_action_from_shell("pwd; git commit -m 'x'") is True
    assert infer_write_action_from_shell("rg foo . || touch marker.txt") is True


def test_infer_write_action_from_shell_quoted_redirection_is_not_write() -> None:
    from github_mcp.command_classification import infer_write_action_from_shell

    # These contain '>' but only as a literal string argument.
    assert infer_write_action_from_shell('rg ">" .') is False
    assert infer_write_action_from_shell("echo '>'") is False

    # Real output redirection remains write.
    assert infer_write_action_from_shell('echo ">" > out.txt') is True
    assert infer_write_action_from_shell("echo hi 2> err.txt") is True


def test_infer_write_action_from_shell_pip_read_only_subcommands() -> None:
    from github_mcp.command_classification import infer_write_action_from_shell

    assert infer_write_action_from_shell("pip check") is False
    assert infer_write_action_from_shell("pip list") is False
    assert infer_write_action_from_shell("pip freeze") is False
    assert infer_write_action_from_shell("python -m pip check") is False
    assert infer_write_action_from_shell("python -m pip list") is False

    assert infer_write_action_from_shell("pip install -r dev-requirements.txt") is True
    assert (
        infer_write_action_from_shell("python -m pip install -r dev-requirements.txt")
        is True
    )


def test_infer_write_action_from_shell_pipeline_write_stage() -> None:
    from github_mcp.command_classification import infer_write_action_from_shell

    assert infer_write_action_from_shell("cat README.md | wc -l") is False
    assert infer_write_action_from_shell("cat README.md | tee out.txt") is True


def _get_resolver(fn: Any) -> Callable[[dict[str, Any]], bool]:
    resolver = getattr(fn, "__mcp_write_action_resolver__", None)
    assert callable(resolver), "expected tool to expose a write_action_resolver"
    return resolver


def test_terminal_command_write_action_resolver_edge_cases() -> None:
    from github_mcp.workspace_tools.commands import terminal_command

    resolver = _get_resolver(terminal_command)

    assert resolver({"command": "pytest -q", "installing_dependencies": False}) is False
    assert resolver({"command": "pip check", "installing_dependencies": False}) is False
    assert (
        resolver({"command": "python -m pip check", "installing_dependencies": False})
        is False
    )
    assert resolver({"command": 'rg ">" .', "installing_dependencies": False}) is False

    assert resolver({"command": "pip install -r dev-requirements.txt"}) is True
    assert resolver({"command": "echo hi > out.txt"}) is True
    # Dependency installation should force write classification.
    assert resolver({"command": "pytest -q", "installing_dependencies": True}) is True


def test_apply_workspace_operations_write_action_resolver_edge_cases() -> None:
    from github_mcp.workspace_tools.fs import apply_workspace_operations

    resolver = _get_resolver(apply_workspace_operations)

    # Preview mode should not require write approval even when the ops are write-capable.
    assert (
        resolver(
            {
                "preview_only": True,
                "operations": [{"op": "write", "path": "x.txt", "content": "hi"}],
            }
        )
        is False
    )

    # Pure read_sections operations are read-only.
    assert (
        resolver(
            {
                "preview_only": False,
                "operations": [
                    {"op": "read_sections", "path": "README.md", "start_line": 1},
                    {"op": "read_sections", "path": "README.md", "start_line": 50},
                ],
            }
        )
        is False
    )

    # Mixed operation sets must be treated as write.
    assert (
        resolver(
            {
                "preview_only": False,
                "operations": [
                    {"op": "read_sections", "path": "README.md", "start_line": 1},
                    {"op": "replace_text", "path": "README.md", "old": "a", "new": "b"},
                ],
            }
        )
        is True
    )

    # Malformed or empty operations should conservatively classify as write-capable.
    assert resolver({"preview_only": False, "operations": []}) is True
    assert resolver({"preview_only": False, "operations": None}) is True
    assert resolver({"preview_only": False}) is True


def test_core_tool_gating_metadata_is_consistent() -> None:
    """Regression tests for tooling/workflow write-action annotations."""

    from github_mcp.workspace_tools.batch import workspace_batch
    from github_mcp.workspace_tools.commands import terminal_command
    from github_mcp.workspace_tools.suites import (
        run_lint_suite,
        run_quality_suite,
        run_tests,
    )
    from github_mcp.workspace_tools.workflows import workspace_apply_ops_and_open_pr

    # Orchestration/workflow tools are inherently write-capable.
    assert bool(getattr(workspace_batch, "__mcp_write_action__", None)) is True
    assert (
        bool(getattr(workspace_apply_ops_and_open_pr, "__mcp_write_action__", None))
        is True
    )

    # Suites are explicitly read-gated even though they may execute commands.
    assert bool(getattr(run_tests, "__mcp_write_action__", None)) is False
    assert bool(getattr(run_lint_suite, "__mcp_write_action__", None)) is False
    assert bool(getattr(run_quality_suite, "__mcp_write_action__", None)) is False

    # Command runner is dynamically gated.
    assert bool(getattr(terminal_command, "__mcp_write_action__", None)) is True
    assert callable(getattr(terminal_command, "__mcp_write_action_resolver__", None))

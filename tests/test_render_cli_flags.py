from github_mcp.main_tools.render_cli import _should_inject_global_flags


def test_should_skip_injection_for_root_help_flag() -> None:
    assert _should_inject_global_flags(["--help"]) is False
    assert _should_inject_global_flags(["-h"]) is False


def test_should_skip_injection_for_root_version_flag() -> None:
    assert _should_inject_global_flags(["--version"]) is False
    assert _should_inject_global_flags(["-v"]) is False


def test_should_inject_for_subcommand_help() -> None:
    assert _should_inject_global_flags(["services", "--help"]) is True


def test_should_inject_for_normal_commands() -> None:
    assert _should_inject_global_flags(["services", "list"]) is True

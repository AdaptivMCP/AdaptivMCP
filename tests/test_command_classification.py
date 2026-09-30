from __future__ import annotations

import pytest

from github_mcp.command_classification import infer_write_action_from_shell


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("", True),
        ("ls -la", False),
        ("cat README.md", False),
        ("rg foo .", False),
        ("rg foo . | wc -l", True),
        ("echo hi > out.txt", True),
        ("echo hi 2>err.txt", True),
        ("echo hi 2>>err.txt", True),
        ("git status", False),
        ("git branch", False),
        ("git branch -d old", True),
        ("git config --global user.name test", True),
        ("git config user.name", False),
        ("sed -n '1,10p' file.txt", False),
        ("sed -i 's/a/b/' file.txt", True),
        ("python -m pip install -r requirements.txt", True),
        ("pytest -q", True),
        ("python -m pytest -q", True),
        ("make test", True),
        ("npm test", True),
        ("npm run lint", True),
        ("ruff check .", False),
        ("ruff check . --fix", True),
        ("ruff format --check .", False),
        ("ruff format .", True),
        ("black --check .", False),
        ("black .", True),
        ("isort --check-only .", False),
        ("isort .", True),
        ("unknown_command --flag", True),
        ("echo hi | less", True),
        ("echo hi | tee out.txt", True),
        ("sudo ls", False),
        ("sudo mkdir -p /tmp/example", True),
    ],
)
def test_infer_write_action_from_shell(command: str, expected: bool) -> None:
    assert infer_write_action_from_shell(command) is expected


def test_infer_write_action_installing_dependencies_forces_write() -> None:
    assert infer_write_action_from_shell("ls", installing_dependencies=True) is True


def test_infer_write_action_uses_command_lines_when_command_empty() -> None:
    assert (
        infer_write_action_from_shell(
            "",
            command_lines=["", "  ", "ls -la"],
        )
        is False
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls -la; whoami", True),
        ("ls -la && echo done", True),
        ("ls -la | wc -l", True),
        ("echo 'a; b'", False),
        ("echo \"a && b\"", False),
        ("echo $(whoami)", True),
        ("echo `whoami`", True),
        ("git remote -v", False),
        ("git remote add origin https://example.invalid/repo.git", True),
        ("git config user.name", False),
        ("git config user.name attacker", True),
        ("git branch -m renamed", True),
    ],
)
def test_shell_classification_is_conservative_for_compound_and_mutating_commands(
    command: str, expected: bool
) -> None:
    assert infer_write_action_from_shell(command) is expected

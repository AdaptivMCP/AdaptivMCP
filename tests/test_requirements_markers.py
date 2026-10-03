"""Runtime requirement edits must invalidate cached development installs."""

from __future__ import annotations

from pathlib import Path

import pytest

from github_mcp.workspace_tools import _shared
from scripts import bootstrap


@pytest.mark.parametrize(
    "include", ["-r requirements.txt", "--requirement=requirements.txt"]
)
def test_runtime_edit_invalidates_development_install(
    tmp_path: Path, include: str
) -> None:
    runtime = tmp_path / "requirements.txt"
    runtime.write_text("fastmcp==3.2.0\n", encoding="utf-8")
    development = tmp_path / "dev-requirements.txt"
    development.write_text(include + "\npytest\n", encoding="utf-8")
    venv = tmp_path / "venv"
    venv.mkdir()

    _shared._write_requirements_marker(str(venv), str(development))
    assert not _shared._should_install_requirements(str(venv), str(development))
    assert not bootstrap._should_install_requirements(
        venv, development, venv_created=False
    )

    runtime.write_text("fastmcp==3.2.4\n", encoding="utf-8")
    assert _shared._should_install_requirements(str(venv), str(development))
    assert bootstrap._should_install_requirements(venv, development, venv_created=False)

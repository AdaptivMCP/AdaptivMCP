import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("argv", [["--version"], ["-h"], []])
def test_main_basic_cli(argv, capsys):
    cli = importlib.import_module("cli")
    exit_code = cli.main(argv)

    # For --version and help, argparse normally calls SystemExit; main now
    # returns that exit code instead, so we expect 0 for these variants.
    assert exit_code == 0
    out, err = capsys.readouterr()
    assert out.strip() != ""
    assert err == ""


def test_doctor_uses_validate_environment_and_summarizes(capsys, monkeypatch):
    cli = importlib.import_module("cli")

    fake_result = {
        "status": "warning",
        "checks": [
            {"name": "github_token", "level": "ok", "message": "GitHub token is configured"},
            {
                "name": "controller_repo_push_permission",
                "level": "warning",
                "message": "Push permission not confirmed",
            },
        ],
    }

    def fake_validate_environment():  # type: ignore[override]
        return fake_result

    fake_main = SimpleNamespace(validate_environment=fake_validate_environment)
    monkeypatch.setitem(importlib.import_module("sys").modules, "main", fake_main)

    exit_code = cli.main(["doctor"])

    assert exit_code == 0
    out, err = capsys.readouterr()

    assert "Status: warning" in out
    assert "Checks: ok=1, warning=1, error=0" in out
    assert "github_token" in out
    assert "controller_repo_push_permission" in out
    assert err == ""

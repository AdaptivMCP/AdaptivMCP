from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _load_project_version(pyproject_path: Path | None = None) -> str:
    """Best-effort loader for the project version from pyproject.toml.

    This avoids importing the server module (and its FastAPI/FastMCP wiring)
    just to answer a simple CLI query like `--version`.
    """
    if pyproject_path is None:
        pyproject_path = Path(__file__).with_name("pyproject.toml")

    try:
        import tomllib  # Python 3.11+
    except Exception:  # pragma: no cover - extremely unlikely on supported runtimes
        return "0.0.0"

    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "0.0.0"
    except Exception:
        # If the file exists but cannot be parsed, fall back to a safe default
        return "0.0.0"

    project = data.get("project") or {}
    version = project.get("version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return "0.0.0"



def _run_doctor() -> int:
    """Run basic environment checks and print a human-readable summary.

    This is a thin wrapper around the `validate_environment` MCP tool so
    operators can quickly confirm configuration and token health from a shell.
    """
    try:
        # Lazy import to avoid pulling in the server module unless needed.
        import main as server_main
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Failed to import server module for doctor: {exc}", file=sys.stderr)
        return 1

    try:
        validate_env = getattr(server_main, "validate_environment")
        result_or_coro = validate_env()
        if asyncio.iscoroutine(result_or_coro):
            result = asyncio.run(result_or_coro)
        else:
            result = result_or_coro
    except Exception as exc:  # pragma: no cover - defensive
        print(f"validate_environment failed: {exc}", file=sys.stderr)
        return 1

    status = str(result.get("status", "unknown"))
    checks = result.get("checks") or []
    ok = sum(1 for c in checks if c.get("level") == "ok")
    warning = sum(1 for c in checks if c.get("level") == "warning")
    error = sum(1 for c in checks if c.get("level") == "error")

    print(f"Status: {status}")
    print(f"Checks: ok={ok}, warning={warning}, error={error}")
    for check in checks:
        name = check.get("name", "?")
        level = check.get("level", "?")
        message = check.get("message", "")
        print(f"- [{level}] {name}: {message}")

    return 0 if status != "error" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adaptiv-controller",
        description="Adaptiv Controller CLI helpers.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the Adaptiv Controller version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "doctor",
        help="Run environment checks (validate_environment) and print a summary.",
    )

    if argv is None:
        argv = sys.argv[1:]

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # When used as a library function in tests, return the exit code
        # instead of raising. The __main__ guard still exits with this code
        # when the CLI is invoked from the shell.
        return int(getattr(exc, "code", 1) or 0)

    if args.version and not args.command:
        print(_load_project_version())
        return 0

    if args.command == "doctor":
        return _run_doctor()

    # Default: show help if no command/flag was given.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

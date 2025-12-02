from __future__ import annotations

import argparse
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

    if argv is None:
        argv = sys.argv[1:]

    args = parser.parse_args(argv)

    if args.version:
        print(_load_project_version())
        return 0

    # For now we keep the CLI intentionally small. This entry point mainly exists
    # to provide a stable `--version` surface that tools and humans can script
    # against. Additional subcommands can be added in future versions.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

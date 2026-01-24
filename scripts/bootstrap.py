"""Project bootstrap helper.

This script creates (or repairs) a local virtual environment and installs
dependencies so contributors can run tests and start the server reliably.

Usage:
  python scripts/bootstrap.py

By default it creates a `.venv` at the repository root and installs
`dev-requirements.txt`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(cmd: list[str], *, cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _pip_ok(python_exe: Path, *, cwd: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python_exe), "-m", "pip", "--version"],
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _ensure_pip(python_exe: Path, *, cwd: Path) -> None:
    if _pip_ok(python_exe, cwd=cwd):
        _run(
            [
                str(python_exe),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
            ],
            cwd=cwd,
        )
        return

    # Bootstrap pip when missing.
    _run([str(python_exe), "-m", "ensurepip", "--upgrade"], cwd=cwd)
    if not _pip_ok(python_exe, cwd=cwd):
        raise SystemExit(
            "pip is unavailable after ensurepip; check your Python installation"
        )
    _run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        cwd=cwd,
    )


def _create_or_repair_venv(
    python: str, *, venv_dir: Path, cwd: Path
) -> tuple[Path, bool]:
    vpy = _venv_python(venv_dir)
    created = False

    if venv_dir.is_dir():
        if not vpy.is_file():
            shutil.rmtree(venv_dir, ignore_errors=True)
        else:
            # Validate pip; if broken, recreate.
            if _pip_ok(vpy, cwd=cwd):
                return vpy, created
            shutil.rmtree(venv_dir, ignore_errors=True)

    # Prefer --upgrade-deps when available.
    cmd = [python, "-m", "venv", "--upgrade-deps", str(venv_dir)]
    proc = subprocess.run(cmd, cwd=str(cwd), check=False)
    if proc.returncode != 0:
        cmd = [python, "-m", "venv", str(venv_dir)]
        _run(cmd, cwd=cwd)

    vpy = _venv_python(venv_dir)
    if not vpy.is_file():
        raise SystemExit("venv creation succeeded but python executable is missing")
    created = True
    return vpy, created


def _requirements_hash(requirements_path: Path) -> str:
    content = requirements_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def _requirements_marker(venv_dir: Path, requirements_path: Path) -> Path:
    marker_name = f".deps-{requirements_path.name}.sha256"
    return venv_dir / marker_name


def _should_install_requirements(
    venv_dir: Path,
    requirements_path: Path,
    *,
    venv_created: bool,
) -> bool:
    if not requirements_path.is_file():
        return False

    if venv_created:
        return True

    marker = _requirements_marker(venv_dir, requirements_path)
    if not marker.is_file():
        return True

    current_hash = _requirements_hash(requirements_path)
    recorded_hash = marker.read_text(encoding="utf-8").strip()
    return current_hash != recorded_hash


def _record_requirements_marker(venv_dir: Path, requirements_path: Path) -> None:
    marker = _requirements_marker(venv_dir, requirements_path)
    marker.write_text(_requirements_hash(requirements_path) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a local development environment"
    )
    parser.add_argument(
        "--python",
        default=os.environ.get("PYTHON", sys.executable),
        help="Python interpreter to use for venv creation (default: current interpreter)",
    )
    parser.add_argument(
        "--venv",
        default=".venv",
        help="Virtualenv directory to create (default: .venv)",
    )
    parser.add_argument(
        "--deps",
        choices=["dev", "prod", "none"],
        default="dev",
        help="Which dependencies to install (default: dev)",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run pytest -q after installing dependencies",
    )
    args = parser.parse_args()

    root = _repo_root()
    venv_dir = (root / args.venv).resolve()

    vpy, venv_created = _create_or_repair_venv(args.python, venv_dir=venv_dir, cwd=root)
    _ensure_pip(vpy, cwd=root)

    if args.deps == "prod" or args.deps == "dev":
        requirements_path = root / "dev-requirements.txt"
        if _should_install_requirements(
            venv_dir,
            requirements_path,
            venv_created=venv_created,
        ):
            _run(
                [str(vpy), "-m", "pip", "install", "-r", str(requirements_path)],
                cwd=root,
            )
            _record_requirements_marker(venv_dir, requirements_path)

    if args.run_tests:
        _run([str(vpy), "-m", "pytest", "-q"], cwd=root)

    activate_hint = (
        f"{venv_dir}\\Scripts\\activate"
        if os.name == "nt"
        else f"source {venv_dir}/bin/activate"
    )
    print("Bootstrap complete.")
    print(f"Activate the venv: {activate_hint}")
    print("Run the server: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

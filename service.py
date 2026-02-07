#!/usr/bin/env python3
"""Service router script for Python projects.

Routes commands to appropriate service scripts from qualitybase or local services.
Usage:
    ./service.py quality lint
    ./service.py dev install-dev
    ENSURE_VIRTUALENV=1 ./service.py dev help
"""

from __future__ import annotations

import os
import platform
import site
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _activate_venv_if_requested() -> None:
    """Activate virtual environment if ENSURE_VIRTUALENV=1 is set."""
    if os.environ.get("ENSURE_VIRTUALENV") != "1":
        return

    venv_dir = PROJECT_ROOT / ".venv"
    if not venv_dir.exists():
        return

    is_windows = platform.system() == "Windows"
    venv_bin = venv_dir / ("Scripts" if is_windows else "bin")
    venv_python = venv_bin / ("python.exe" if is_windows else "python")

    if not venv_python.exists():
        return

    sys.executable = str(venv_python)
    _update_path(venv_bin, is_windows)
    _add_site_packages(venv_dir, is_windows)


def _update_path(venv_bin: Path, is_windows: bool) -> None:
    """Update PATH environment variable to include venv bin directory."""
    path_sep = ";" if is_windows else ":"
    current_path = os.environ.get("PATH", "")
    venv_bin_str = str(venv_bin)
    if venv_bin_str not in current_path:
        os.environ["PATH"] = f"{venv_bin_str}{path_sep}{current_path}"


def _add_site_packages(venv_dir: Path, is_windows: bool) -> None:
    """Add site-packages directories to Python path."""
    if is_windows:
        site_packages = venv_dir / "Lib" / "site-packages"
        if site_packages.exists():
            site.addsitedir(str(site_packages))
    else:
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        for lib_dir in ["lib", "lib64"]:
            site_packages = venv_dir / lib_dir / f"python{python_version}" / "site-packages"
            if site_packages.exists():
                site.addsitedir(str(site_packages))


def main() -> int:
    """Main entry point."""
    _activate_venv_if_requested()

    try:
        from qualitybase.services.service import main as service_main
    except ImportError as e:
        print("Error: qualitybase not found. Either install qualitybase as a dependency or ensure it's available in the development environment.")
        print(f"\nDetails: {e}")
        print("\nTo fix this, install dependencies from requirements.txt:")
        requirements = PROJECT_ROOT / "requirements.txt"
        if requirements.exists():
            print(f"     pip install -r {requirements}")
        else:
            print("     pip install -r requirements.txt")
        print("\nOr if you have additionallib.json, install qualitybase manually:")
        print("     pip install -e ../python-qualitybase")
        return 1

    return service_main(PROJECT_ROOT, usage_prefix="./service.py")


if __name__ == "__main__":
    sys.exit(main())

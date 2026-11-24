"""Run local checks for the packages in this repository."""

import os
import shlex
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = "*/migrations/*"


class Audit:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.skipped: list[str] = []

    def run(self, name: str, cwd: Path, *command: str) -> None:
        display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        print(f"\n## {name} ({cwd.relative_to(ROOT)})\n\n$ {display}\n", flush=True)
        try:
            result = subprocess.run(command, cwd=cwd, check=False)
        except OSError as exc:
            print(f"Could not start command: {exc}", flush=True)
            self.failures.append(f"{name}: {exc}")
            return
        print(f"\nExit status: {result.returncode}", flush=True)
        if result.returncode:
            self.failures.append(f"{name}: exit {result.returncode}")

    def module(self, name: str, cwd: Path, tool: str, *args: str) -> None:
        self.run(name, cwd, sys.executable, "-m", tool, *args)

    def tests(self, package: Path) -> None:
        label = package.relative_to(ROOT)
        tests = package / "tests"
        if tests.is_dir() and any(tests.rglob("test*.py")):
            extra = ("--ds=tests.settings",) if (tests / "settings.py").is_file() else ()
            if (package / "manage.py").is_file():
                extra += (
                    "-W",
                    "error::django.core.paginator.UnorderedObjectListWarning",
                )
            self.module(
                f"{label}: tests and branch coverage",
                package,
                "pytest",
                "--tb=line",
                "--cov=src",
                "--cov-branch",
                "--cov-report=term",
                "-W",
                "error::ResourceWarning",
                "-W",
                "error::pytest.PytestUnraisableExceptionWarning",
                *extra,
            )
        else:
            self.skipped.append(f"{label}: no Python tests found")

        widget_tests = tests / "flag_widget.test.cjs"
        if widget_tests.is_file():
            self.run(
                f"{label}: JavaScript tests",
                package,
                "node",
                "--test",
                str(widget_tests),
            )

    def build(self, package: Path) -> None:
        label = package.relative_to(ROOT)
        with TemporaryDirectory(prefix="package-audit-") as directory:
            self.module(f"{label}: build", package, "build", "--outdir", directory)
            distributions = sorted(path for path in Path(directory).iterdir() if path.is_file())
            if not any(path.suffix == ".whl" for path in distributions):
                self.failures.append(f"{label}: build produced no wheel")
            if not any(path.name.endswith(".tar.gz") for path in distributions):
                self.failures.append(f"{label}: build produced no source archive")
            if distributions:
                self.module(
                    f"{label}: distribution metadata",
                    package,
                    "twine",
                    "check",
                    *map(str, distributions),
                )
            else:
                self.failures.append(f"{label}: build produced no distributions")
            package_name = "pymissive" if package.name == "python-pymissive" else package.name
            for wheel in (path for path in distributions if path.suffix == ".whl"):
                self.run(
                    f"{label}: wheel contents",
                    ROOT,
                    sys.executable,
                    ".github/scripts/check-wheel-contents.py",
                    "--package",
                    package_name,
                    str(wheel),
                )

    def package(self, package: Path) -> None:
        label = package.relative_to(ROOT)
        if not (package / "src").is_dir():
            self.failures.append(f"{label}: missing src directory")
            return
        if (package / "manage.py").is_file():
            self.run(f"{label}: Django check", package, sys.executable, "manage.py", "check")
        self.tests(package)
        self.module(
            f"{label}: Bandit",
            package,
            "bandit",
            "-r",
            "src",
            "-x",
            MIGRATIONS,
            "-ll",
            "-ii",
        )
        self.module(f"{label}: dependency audit", package, "pip_audit", ".")
        self.module(
            f"{label}: dead code",
            package,
            "vulture",
            "src",
            "--min-confidence",
            "90",
            "--exclude",
            MIGRATIONS,
        )
        self.module(
            f"{label}: complexity inventory",
            package,
            "radon",
            "cc",
            "src",
            "-s",
            "-a",
            "-e",
            MIGRATIONS,
        )
        self.module(
            f"{label}: maintainability",
            package,
            "radon",
            "mi",
            "src",
            "-s",
            "-e",
            MIGRATIONS,
        )
        self.module(
            f"{label}: code size",
            package,
            "radon",
            "raw",
            "src",
            "-s",
            "-e",
            MIGRATIONS,
        )
        self.module(
            f"{label}: complexity thresholds",
            package,
            "xenon",
            "src",
            "--exclude",
            MIGRATIONS,
            "--max-absolute",
            "C",
            "--max-modules",
            "B",
            "--max-average",
            "A",
        )
        self.module(f"{label}: typing", package, "mypy", "src")
        self.build(package)


def main() -> int:
    packages = (
        [ROOT] if (ROOT / "pyproject.toml").is_file() else sorted(path.parent for path in ROOT.glob("*/pyproject.toml"))
    )
    if not packages:
        print("No Python packages found.", file=sys.stderr)
        return 1
    audit = Audit()
    audit.run("Git whitespace", ROOT, "git", "diff", "--check")
    audit.module("Ruff lint", ROOT, "ruff", "check", ".")
    audit.module("Ruff format", ROOT, "ruff", "format", "--check", ".")
    for package in packages:
        audit.package(package)
    print("\n## Summary")
    for message in audit.skipped:
        print(f"WARNING: {message}")
    if audit.failures:
        for failure in audit.failures:
            print(f"FAILED: {failure}")
        return 1
    print("All executed checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

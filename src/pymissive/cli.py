"""Command-line interface with automatic command discovery."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from qualitybase.cli import (
    CommandInfo,
    _get_package_name_from_path,
    cli_main,
    discover_commands,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

cli_file_path = Path(__file__)



def _discover_commands() -> dict[str, CommandInfo]:
    """Discover commands using default cli file path."""
    result: dict[str, CommandInfo] = discover_commands(cli_file_path)
    return result


def _get_package_name() -> str:
    """Get package name using default cli file path."""
    result: str = _get_package_name_from_path(cli_file_path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    result = cli_main(cli_file_path, argv)
    return int(result) if isinstance(result, (int, bool)) else (0 if result else 1)


if __name__ == "__main__":
    sys.exit(main())

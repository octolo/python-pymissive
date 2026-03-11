"""Command-line interface with automatic command discovery."""

from __future__ import annotations

import sys
from pathlib import Path

from clicommands.helpers import cli_main


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    cli_file_path = Path(__file__)
    result = cli_main(cli_file_path, argv)
    return int(result) if isinstance(result, (int, bool)) else (0 if result else 1)


if __name__ == "__main__":
    sys.exit(main())

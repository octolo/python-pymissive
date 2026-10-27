"""Command-line interface with automatic command discovery."""

from __future__ import annotations

import sys
from pathlib import Path

from clicommands.helpers import cli_main


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    args = list(argv) if argv is not None else sys.argv[1:]

    # --help / -h: show README or command doc
    if args and args[0] in ("--help", "-h"):
        from pymissive.commands.help import print_readme

        success = print_readme()
        return 0 if success else 1

    # If command is X and next arg is --help, let the command handle it
    cli_file_path = Path(__file__)
    result = cli_main(cli_file_path, args)
    return int(result) if isinstance(result, (int, bool)) else (0 if result else 1)


if __name__ == "__main__":
    sys.exit(main())

"""Recipient command - validate and format recipients."""

from __future__ import annotations

import json
import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command

_ARG_CONFIG = {
    "help": {"type": "store_true"},
    "recipients": {"type": str, "default": ""},
    "format": {"type": str, "default": "json"},
}


def _recipient_command(args: list[str]) -> bool:
    """Validate and format recipient data."""
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="recipient")
    if parsed.get("help"):
        from .help import print_command_help
        return print_command_help("recipient")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else "validate"

    recipients_raw = parsed.get("recipients", "")
    if not recipients_raw:
        print("Error: --recipients required (JSON array)", file=sys.stderr)
        return False
    try:
        recipients = json.loads(recipients_raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return False
    if not isinstance(recipients, list):
        print("Error: recipients must be a JSON array", file=sys.stderr)
        return False

    if subcommand == "validate":
        valid = []
        for i, r in enumerate(recipients):
            if isinstance(r, dict):
                if "email" in r or "phone" in r or "address" in r:
                    valid.append(r)
                else:
                    print(f"Warning: recipient[{i}] missing email/phone/address", file=sys.stderr)
            else:
                print(f"Warning: recipient[{i}] must be object", file=sys.stderr)
        print(json.dumps(valid, indent=2))
    elif subcommand == "format":
        print(json.dumps(recipients, indent=2))
    else:
        print(f"Error: Unknown subcommand '{subcommand}'. Use: validate, format", file=sys.stderr)
        return False

    return True


recipient_command = Command(
    _recipient_command,
    "Validate/format recipients (recipient validate --recipients '[{\"email\":\"x@y.com\"}]')",
)

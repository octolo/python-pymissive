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


def _parse_recipients(raw: str) -> list | None:
    if not raw:
        print("Error: --recipients required (JSON array)", file=sys.stderr)
        return None
    try:
        recipients = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(recipients, list):
        print("Error: recipients must be a JSON array", file=sys.stderr)
        return None
    return recipients


def _valid_recipients(recipients: list) -> list:
    valid = []
    for index, recipient in enumerate(recipients):
        if not isinstance(recipient, dict):
            print(f"Warning: recipient[{index}] must be object", file=sys.stderr)
        elif {"email", "phone", "address"} & recipient.keys():
            valid.append(recipient)
        else:
            print(f"Warning: recipient[{index}] missing email/phone/address", file=sys.stderr)
    return valid


def _recipient_command(args: list[str]) -> bool:
    """Validate and format recipient data."""
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="recipient")
    if parsed.get("help"):
        from .help import print_command_help

        return print_command_help("recipient")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else "validate"

    recipients = _parse_recipients(parsed.get("recipients", ""))
    if recipients is None:
        return False

    if subcommand == "validate":
        print(json.dumps(_valid_recipients(recipients), indent=2))
    elif subcommand == "format":
        print(json.dumps(recipients, indent=2))
    else:
        print(f"Error: Unknown subcommand '{subcommand}'. Use: validate, format", file=sys.stderr)
        return False

    return True


recipient_command = Command(
    _recipient_command,
    'Validate/format recipients (recipient validate --recipients \'[{"email":"x@y.com"}]\')',
)

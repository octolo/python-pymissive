"""Webhook command — generate an opt-in WEBHOOK_SECRET."""

from __future__ import annotations

import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command
from clicommands.utils import print_header, print_separator

from pymissive.webhook_secret import collect_mouse_entropy, generate_webhook_secret

_ARG_CONFIG = {
    "help": {"type": "store_true"},
    "provider": {"type": str, "default": ""},
    "seconds": {"type": float, "default": 5},
}


def _webhook_command(args: list[str]) -> bool:
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="webhook")
    if parsed.get("help"):
        from .help import print_command_help

        return print_command_help("webhook")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else "secret"
    provider = parsed.get("provider") or ""
    seconds = parsed.get("seconds") or 5

    if subcommand != "secret":
        print(
            f"Error: Unknown subcommand '{subcommand}'. Use: secret",
            file=sys.stderr,
        )
        return False
    if not provider:
        print("Error: --provider required", file=sys.stderr)
        return False

    print(
        f"Move the mouse for {seconds:g}s (window will close by itself)…",
        file=sys.stderr,
    )
    try:
        extra = collect_mouse_entropy(float(seconds))
        token = generate_webhook_secret(provider, extra)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False

    print_separator()
    print_header(f"{provider} - webhook secret")
    print_separator()
    print(token)
    print(
        "Set WEBHOOK_SECRET (or BREVO_WEBHOOK_SECRET / …) to this value.",
        file=sys.stderr,
    )
    return True


webhook_command = Command(
    _webhook_command,
    "Generate a webhook secret (webhook secret --provider brevo [--seconds 5])",
)

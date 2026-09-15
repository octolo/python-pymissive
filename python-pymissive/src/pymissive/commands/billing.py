"""Billing command - retrieve billing/usage data from provider."""

from __future__ import annotations

import json
import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command
from clicommands.utils import print_header, print_separator
from providerkit.commands.provider import _PROVIDER_COMMAND_CONFIG
from providerkit.helpers import get_providers

_ARG_CONFIG = {
    **_PROVIDER_COMMAND_CONFIG,
    "help": {"type": "store_true"},
    "provider": {"type": str, "default": ""},
    "type": {"type": str, "default": ""},
    "missive_type": {"type": str, "default": ""},
    "external_id": {"type": str, "default": ""},
    "start_date": {"type": str, "default": ""},
    "end_date": {"type": str, "default": ""},
}


def _billing_command(args: list[str]) -> bool:
    """Retrieve billing data from provider."""
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="billing")
    if parsed.get("help"):
        from .help import print_command_help
        return print_command_help("billing")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else "retrieve"
    provider_name = parsed.get("provider") or parsed.get("filter") or parsed.get("backend", "")
    missive_type = parsed.get("type") or parsed.get("missive_type", "lre")
    external_id = parsed.get("external_id", "")
    start_date = parsed.get("start_date") or ""
    end_date = parsed.get("end_date") or ""

    if not provider_name:
        print("Error: --provider required", file=sys.stderr)
        return False

    kwargs = {"lib_name": "pymissive", "attribute_search": {"name": provider_name}}
    if parsed.get("dir"):
        kwargs["dir_path"] = parsed["dir"]
    if parsed.get("json"):
        kwargs["json"] = parsed["json"]

    providers = get_providers(**kwargs)
    if not providers:
        print(f"Error: Provider '{provider_name}' not found", file=sys.stderr)
        return False
    provider = providers[0]

    if subcommand == "retrieve":
        if start_date or end_date:
            if not start_date or not end_date:
                print("Error: --start-date and --end-date required for bulk billing retrieve", file=sys.stderr)
                return False
            if not missive_type:
                print("Error: --type required for retrieve billings (e.g. lre)", file=sys.stderr)
                return False
            service = f"retrieve_billings_{missive_type}"
            if not hasattr(provider, service):
                print(f"Error: Provider does not support {service}", file=sys.stderr)
                return False
            provider.call_service(service, start_date=start_date, end_date=end_date)
            data = provider.get_service_normalize(service)
        else:
            service = f"get_billings_{missive_type}"
            if hasattr(provider, service):
                payload = {"external_id": external_id} if external_id else {}
                provider.call_service(service, **payload)
                data = provider.get_service_normalize(service)
            elif hasattr(provider, "retrieve_billing"):
                provider.call_service("retrieve_billing")
                data = provider.get_service_normalize("retrieve_billing")
            else:
                print("Error: Provider does not support billing retrieval", file=sys.stderr)
                return False
        print_separator()
        print_header(f"{provider_name} - billing")
        print_separator()
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"Error: Unknown subcommand '{subcommand}'. Use: retrieve", file=sys.stderr)
        return False

    return True


billing_command = Command(
    _billing_command,
    "Retrieve billing/usage data (billing retrieve --provider X [--start-date D --end-date D | --external-id ID])",
)

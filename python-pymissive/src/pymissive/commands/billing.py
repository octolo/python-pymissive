"""Billing command - retrieve billing/usage data from provider."""

from __future__ import annotations

import json
import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command
from clicommands.utils import print_header, print_separator
from providerkit.commands.provider import _PROVIDER_COMMAND_CONFIG
from providerkit.helpers import get_providers
from pymissive.config import provider_service_name


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


def _get_provider(parsed):
    provider_name = parsed.get("provider") or parsed.get("filter") or parsed.get("backend", "")
    if not provider_name:
        print("Error: --provider required", file=sys.stderr)
        return None
    kwargs = {"lib_name": "pymissive", "attribute_search": {"name": provider_name}}
    if parsed.get("dir"):
        kwargs["dir_path"] = parsed["dir"]
    if parsed.get("json"):
        kwargs["json"] = parsed["json"]
    providers = get_providers(**kwargs)
    if not providers:
        print(f"Error: Provider '{provider_name}' not found", file=sys.stderr)
        return None
    return provider_name, providers[0]


def _service_name(action, missive_type):
    try:
        return provider_service_name(action, missive_type)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ""


def _retrieve_bulk_billing(parsed, provider, missive_type):
    start_date = parsed.get("start_date") or ""
    end_date = parsed.get("end_date") or ""
    if not start_date or not end_date:
        print("Error: --start-date and --end-date required for bulk billing retrieve", file=sys.stderr)
        return False, None
    if not missive_type:
        print("Error: --type required for retrieve billings (e.g. registered_letter)", file=sys.stderr)
        return False, None
    service = _service_name("retrieve_billings", missive_type)
    if not service:
        return False, None
    if not hasattr(provider, service):
        print(f"Error: Provider does not support {service}", file=sys.stderr)
        return False, None
    provider.call_service(service, start_date=start_date, end_date=end_date)
    return True, provider.get_service_normalize(service)


def _retrieve_single_billing(parsed, provider, missive_type):
    service = _service_name("get_billings", missive_type)
    if not service:
        return False, None
    if hasattr(provider, service):
        external_id = parsed.get("external_id", "")
        payload = {"external_id": external_id} if external_id else {}
        provider.call_service(service, **payload)
        return True, provider.get_service_normalize(service)
    if hasattr(provider, "retrieve_billing"):
        provider.call_service("retrieve_billing")
        return True, provider.get_service_normalize("retrieve_billing")
    print("Error: Provider does not support billing retrieval", file=sys.stderr)
    return False, None


def _billing_options(parsed):
    command_args = parsed.get("args") or []
    subcommand = command_args[0] if command_args else "retrieve"
    missive_type = parsed.get("type") or parsed.get("missive_type") or "registered_letter"
    has_period = bool(parsed.get("start_date") or parsed.get("end_date"))
    return subcommand, missive_type, has_period


def _billing_command(args: list[str]) -> bool:
    """Retrieve billing data from provider."""
    args = [f"--{arg[2:].replace('-', '_')}" if arg.startswith("--") else arg for arg in args]
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="billing")
    if parsed.get("help"):
        from .help import print_command_help

        return print_command_help("billing")
    subcommand, missive_type, has_period = _billing_options(parsed)
    provider_result = _get_provider(parsed)
    if not provider_result:
        return False
    provider_name, provider = provider_result

    if subcommand != "retrieve":
        print(f"Error: Unknown subcommand '{subcommand}'. Use: retrieve", file=sys.stderr)
        return False
    if has_period:
        success, data = _retrieve_bulk_billing(parsed, provider, missive_type)
    else:
        success, data = _retrieve_single_billing(parsed, provider, missive_type)
    if not success:
        return False
    print_separator()
    print_header(f"{provider_name} - billing")
    print_separator()
    print(json.dumps(data, indent=2, default=str))
    return True


billing_command = Command(
    _billing_command,
    "Retrieve billing/usage data (billing retrieve --provider X [--start-date D --end-date D | --external-id ID])",
)

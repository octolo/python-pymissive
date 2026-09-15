"""Attachment command - manage attachments via provider."""

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
    "external_id": {"type": str, "default": ""},
    "document_id": {"type": str, "default": ""},
}


def _attachment_command(args: list[str]) -> bool:
    """Manage attachments via provider."""
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="attachment")
    if parsed.get("help"):
        from .help import print_command_help
        return print_command_help("attachment")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else "retrieve"

    provider_name = parsed.get("provider") or parsed.get("filter") or parsed.get("backend", "")

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
        if hasattr(provider, "retrieve_attachments"):
            provider.call_service("retrieve_attachments")
            data = provider.get_service_normalize("retrieve_attachments")
        elif hasattr(provider, "get_attachments_lre"):
            ext_id = parsed.get("external_id", "")
            if not ext_id:
                print("Error: --external-id required for LRE attachments", file=sys.stderr)
                return False
            data = provider.get_attachments_lre(external_id=ext_id)
        else:
            print("Error: Provider does not support attachment retrieval", file=sys.stderr)
            return False
        print_separator()
        print_header(f"{provider_name} - attachments")
        print_separator()
        print(json.dumps(data, indent=2, default=str))
    elif subcommand == "add":
        print("Error: add attachment not yet implemented (requires --file)", file=sys.stderr)
        return False
    elif subcommand == "delete":
        external_id = parsed.get("external_id", "")
        document_id = parsed.get("document_id", "")
        if not external_id or not document_id:
            print("Error: --external-id and --document-id required for delete", file=sys.stderr)
            return False
        if hasattr(provider, "delete_attachment_lre"):
            provider.delete_attachment_lre(external_id=external_id, document_id=document_id)
            print("Attachment deleted.")
        else:
            print("Error: Provider does not support delete_attachment_lre", file=sys.stderr)
            return False
    else:
        print(f"Error: Unknown subcommand '{subcommand}'. Use: retrieve, add, delete", file=sys.stderr)
        return False

    return True


attachment_command = Command(
    _attachment_command,
    "Manage attachments (attachment retrieve --provider X)",
)

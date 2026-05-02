"""Missive command - create, send, update, delete (webhook or missive), cancel via provider."""

from __future__ import annotations

import json
import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command
from clicommands.utils import print_header, print_separator
from providerkit.commands.provider import _PROVIDER_COMMAND_CONFIG
from providerkit.helpers import get_providers

from pymissive.config import get_missive_send_arg_config

_SEND_ARG_CONFIG = get_missive_send_arg_config()
_COMMAND_ARG_CONFIG = {
    "provider": {"type": str, "default": ""},
    "type": {"type": str, "default": ""},
    "missive_type": {"type": str, "default": ""},
    "webhook_id": {"type": str, "default": ""},
    "external_id": {"type": str, "default": ""},
    "scheme": {"type": str, "default": "https"},
    "domain": {"type": str, "default": "localhost:8080"},
}
_ARG_CONFIG = {
    **_PROVIDER_COMMAND_CONFIG,
    "help": {"type": "store_true"},
    **_SEND_ARG_CONFIG,
    **_COMMAND_ARG_CONFIG,
}



def _parse_json(value: str):
    val = (value or "").strip() if value is not None else ""
    if not val:
        return None
    try:
        return json.loads(val)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return None


def _get_provider(parsed: dict) -> tuple | None:
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


def _missive_command(args: list[str]) -> bool:
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="missive")
    if parsed.get("help"):
        from .help import print_command_help
        return print_command_help("missive")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else ""
    resource = cmd_args[1] if len(cmd_args) > 1 else ""

    if subcommand not in ("create", "retrieve", "send", "update", "delete", "cancel"):
        print("Error: Use create, retrieve, send, update, delete, cancel", file=sys.stderr)
        return False

    result = _get_provider(parsed)
    if not result:
        return False
    provider_name, provider = result
    missive_type = parsed.get("type") or parsed.get("missive_type", "")

    if subcommand == "send":
        if not missive_type:
            print("Error: --missive-type required (e.g. email, sms, lre)", file=sys.stderr)
            return False
        recipients_raw = parsed.get("recipients") or ""
        recipients = _parse_json(recipients_raw) if recipients_raw else None
        if recipients is not None and not isinstance(recipients, list):
            print("Error: --recipients must be a JSON array", file=sys.stderr)
            return False
        if not recipients:
            rec_email = (parsed.get("recipient_email") or "").strip()
            rec_phone = (parsed.get("recipient_phone") or "").strip()
            rec_address_raw = (parsed.get("recipient_address") or "").strip()
            rec_address = _parse_json(rec_address_raw) if rec_address_raw else None
            rec_name = (parsed.get("recipient_name") or "").strip()
            if rec_email:
                recipients = [{"email": rec_email, "name": rec_name or ""}]
            elif rec_phone:
                recipients = [{"phone": rec_phone, "name": rec_name or ""}]
            elif rec_address:
                recipients = [{"address": rec_address, "name": rec_name or ""}]
            else:
                print("Error: --recipients (JSON array) or one of --recipient-email/phone/address required", file=sys.stderr)
                return False
        sender_email = (parsed.get("sender_email") or "").strip()
        sender_name = (parsed.get("sender_name") or "").strip()
        sender_phone = (parsed.get("sender_phone") or "").strip()
        sender_address_raw = (parsed.get("sender_address") or "").strip()
        sender_address = _parse_json(sender_address_raw) if sender_address_raw else None
        sender = {
            "email": sender_email or None,
            "name": sender_name or None,
            "phone": sender_phone or None,
            "address": sender_address,
        }
        sender = {k: v for k, v in sender.items() if v is not None}
        body_text = (parsed.get("body_text") or "") or (parsed.get("body") or "")
        payload = {
            "subject": parsed.get("subject", ""),
            "body_html": parsed.get("body_html", ""),
            "body_text": body_text,
            "recipients": recipients,
            "sender": sender,
            "sender_email": sender_email,
            "sender_name": sender_name,
        }
        payload = {k: v for k, v in payload.items() if v}
        service = f"send_{missive_type}"
        if not hasattr(provider, service):
            print(f"Error: Provider does not support {service}", file=sys.stderr)
            return False
        try:
            provider.call_service(service, **payload)
            print_separator()
            print_header(f"{provider_name} - {missive_type}")
            print_separator()
            print(provider.response(service, parsed.get("raw") or False, output_format=parsed.get("format") or "terminal"))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return False

    elif subcommand == "create":
        if resource == "webhook" or not resource:
            if not missive_type:
                print("Error: --type required for webhook (e.g. email, sms)", file=sys.stderr)
                return False
            scheme = parsed.get("scheme", "https")
            domain = parsed.get("domain", "localhost:8080")
            path = f"/webhook/{provider_name}/{missive_type}/"
            url = f"{scheme}://{domain.rstrip('/')}{path}"
            webhook_data = {"id": "", "type": missive_type, "url": url}
            service = f"create_webhook_{missive_type}"
            if not hasattr(provider, service):
                print(f"Error: Provider does not support {service}", file=sys.stderr)
                return False
            result_id = provider.call_service(service, webhook_data=webhook_data)
            print_separator()
            print_header(f"{provider_name} - created webhook")
            print_separator()
            print(f"webhook_id={result_id}")
        else:
            print(f"Error: Unknown resource '{resource}'. Use: webhook", file=sys.stderr)
            return False

    elif subcommand == "update":
        if resource == "webhook" or not resource:
            webhook_id = parsed.get("webhook_id", "")
            if not webhook_id or not missive_type:
                print("Error: --webhook-id and --type required for webhook update", file=sys.stderr)
                return False
            scheme = parsed.get("scheme", "https")
            domain = parsed.get("domain", "localhost:8080")
            path = f"/webhook/{provider_name}/{missive_type}/"
            url = f"{scheme}://{domain.rstrip('/')}{path}"
            webhook_data = {"id": webhook_id, "type": missive_type, "url": url}
            service = f"update_webhook_{missive_type}"
            if not hasattr(provider, service):
                print(f"Error: Provider does not support {service}", file=sys.stderr)
                return False
            provider.call_service(service, webhook_data=webhook_data)
            print("Webhook updated.")
        else:
            print(f"Error: Unknown resource '{resource}'. Use: webhook", file=sys.stderr)
            return False

    elif subcommand == "delete":
        if resource in ("missive", "sending"):
            external_id = parsed.get("external_id", "")
            if not external_id:
                print(
                    "Error: --external-id required for delete missive",
                    file=sys.stderr,
                )
                return False
            if not missive_type:
                missive_type = "lre"
            service = f"delete_{missive_type}"
            if not hasattr(provider, service):
                print(f"Error: Provider does not support {service}", file=sys.stderr)
                return False
            try:
                result = provider.call_service(service, external_id=external_id)
                print_separator()
                print_header(f"{provider_name} - deleted {missive_type} sending")
                print_separator()
                print(json.dumps(result, indent=2, default=str))
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                return False
        elif resource == "webhook" or not resource:
            webhook_id = parsed.get("webhook_id", "")
            if not webhook_id or not missive_type:
                print("Error: --webhook-id and --type required for webhook delete", file=sys.stderr)
                return False
            webhook_data = {"id": webhook_id, "type": missive_type}
            service = f"delete_webhook_{missive_type}"
            if not hasattr(provider, service):
                print(f"Error: Provider does not support {service}", file=sys.stderr)
                return False
            provider.call_service(service, webhook_data=webhook_data)
            print("Webhook deleted.")
        else:
            print(
                f"Error: Unknown resource '{resource}'. Use: webhook, missive",
                file=sys.stderr,
            )
            return False

    elif subcommand == "retrieve":
        retrieve_resource = resource or "webhooks"
        if retrieve_resource == "webhooks":
            if not hasattr(provider, "retrieve_webhooks"):
                print("Error: Provider does not support retrieve_webhooks", file=sys.stderr)
                return False
            provider.call_service("retrieve_webhooks")
            data = provider.get_service_normalize("retrieve_webhooks")
        elif retrieve_resource == "email":
            if not hasattr(provider, "retrieve_email"):
                print("Error: Provider does not support retrieve_email", file=sys.stderr)
                return False
            provider.call_service("retrieve_email")
            data = provider.get_service_normalize("retrieve_email")
        elif retrieve_resource == "lre":
            if not hasattr(provider, "retrieve_lre"):
                print("Error: Provider does not support retrieve_lre", file=sys.stderr)
                return False
            provider.call_service("retrieve_lre")
            data = provider.get_service_normalize("retrieve_lre")
        elif retrieve_resource == "sms":
            if not hasattr(provider, "retrieve_sms"):
                print("Error: Provider does not support retrieve_sms", file=sys.stderr)
                return False
            provider.call_service("retrieve_sms")
            data = provider.get_service_normalize("retrieve_sms")
        else:
            print("Error: Use webhooks, email, lre, sms (e.g. missive retrieve webhooks --provider X)", file=sys.stderr)
            return False
        print_separator()
        print_header(f"{provider_name} - {retrieve_resource}")
        print_separator()
        print(json.dumps(data, indent=2, default=str))

    elif subcommand == "cancel":
        external_id = parsed.get("external_id", "")
        if not external_id:
            print("Error: --external-id required for cancel", file=sys.stderr)
            return False
        if not missive_type:
            missive_type = "lre"
        service = f"cancel_{missive_type}"
        if not hasattr(provider, service):
            print(f"Error: Provider does not support {service}", file=sys.stderr)
            return False
        try:
            result = provider.call_service(service, external_id=external_id)
            print_separator()
            print_header(f"{provider_name} - cancelled {missive_type}")
            print_separator()
            print(json.dumps(result, indent=2, default=str))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return False

    return True


missive_command = Command(
    _missive_command,
    "Missive: create, retrieve, send, update, delete (webhook/missive), cancel (missive send --provider X --missive-type email --recipients '[...]')",
)

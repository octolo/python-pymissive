"""Missive command - create, send, update, delete (webhook or missive), cancel via provider."""

from __future__ import annotations

import json
import sys

from clicommands.commands.args import parse_args_from_config
from clicommands.commands.base import Command
from clicommands.utils import print_header, print_separator
from providerkit.commands.provider import _PROVIDER_COMMAND_CONFIG
from providerkit.helpers import get_providers

from pymissive.config import get_missive_send_arg_config, provider_service_name

_SEND_ARG_CONFIG = get_missive_send_arg_config()
_COMMAND_ARG_CONFIG = {
    "provider": {"type": str, "default": ""},
    "type": {"type": str, "default": ""},
    "missive_type": {"type": str, "default": ""},
    "webhook_id": {"type": str, "default": ""},
    "external_id": {"type": str, "default": ""},
    "start_date": {"type": str, "default": ""},
    "end_date": {"type": str, "default": ""},
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


def _supports(provider, service: str) -> bool:
    if hasattr(provider, service):
        return True
    print(f"Error: Provider does not support {service}", file=sys.stderr)
    return False


def _print_json_result(title: str, result) -> None:
    print_separator()
    print_header(title)
    print_separator()
    print(json.dumps(result, indent=2, default=str))


def _single_recipient(parsed: dict) -> list[dict] | None:
    name = (parsed.get("recipient_name") or "").strip()
    fields = (
        ("email", (parsed.get("recipient_email") or "").strip()),
        ("phone", (parsed.get("recipient_phone") or "").strip()),
    )
    for field, value in fields:
        if value:
            return [{field: value, "name": name}]
    address_raw = (parsed.get("recipient_address") or "").strip()
    address = _parse_json(address_raw) if address_raw else None
    if address:
        return [{"address": address, "name": name}]
    return None


def _recipients(parsed: dict) -> list | None:
    recipients_raw = parsed.get("recipients") or ""
    recipients = _parse_json(recipients_raw) if recipients_raw else None
    if recipients is not None and not isinstance(recipients, list):
        print("Error: --recipients must be a JSON array", file=sys.stderr)
        return None
    recipients = recipients or _single_recipient(parsed)
    if not recipients:
        print(
            "Error: --recipients (JSON array) or one of --recipient-email/phone/address required",
            file=sys.stderr,
        )
    return recipients


def _text_arg(parsed: dict, name: str) -> str:
    return (parsed.get(name) or "").strip()


def _optional_json_arg(parsed: dict, name: str):
    raw = _text_arg(parsed, name)
    return _parse_json(raw) if raw else None


def _sender_payload(parsed: dict) -> tuple[dict, str, str]:
    sender_email = _text_arg(parsed, "sender_email")
    sender_name = _text_arg(parsed, "sender_name")
    sender = {
        "email": sender_email,
        "name": sender_name,
        "phone": _text_arg(parsed, "sender_phone"),
    }
    sender = {key: value for key, value in sender.items() if value}
    sender_address = _optional_json_arg(parsed, "sender_address")
    if sender_address is not None:
        sender["address"] = sender_address
    return sender, sender_email, sender_name


def _send_payload(parsed: dict, recipients: list) -> dict:
    sender, sender_email, sender_name = _sender_payload(parsed)
    body_text = parsed.get("body_text") or parsed.get("body") or ""
    payload = {
        "subject": parsed.get("subject", ""),
        "body_rich": parsed.get("body_rich", ""),
        "body_text": body_text,
        "recipients": recipients,
        "sender": sender,
        "sender_email": sender_email,
        "sender_name": sender_name,
    }
    return {key: value for key, value in payload.items() if value}


def _send(parsed, provider_name, provider, missive_type, resource) -> bool:
    if not missive_type:
        print("Error: --missive-type required (e.g. email, sms, registered_letter)", file=sys.stderr)
        return False
    recipients = _recipients(parsed)
    if not recipients:
        return False
    service = provider_service_name("send", missive_type)
    if not _supports(provider, service):
        return False
    try:
        provider.call_service(service, **_send_payload(parsed, recipients))
        print_separator()
        print_header(f"{provider_name} - {missive_type}")
        print_separator()
        print(provider.response(service, parsed.get("raw") or False, output_format=parsed.get("format") or "terminal"))
        return True
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False


def _webhook_data(parsed, provider_name, missive_type, webhook_id="") -> dict:
    scheme = parsed.get("scheme", "https")
    domain = parsed.get("domain", "localhost:8080")
    url = f"{scheme}://{domain.rstrip('/')}/webhook/{provider_name}/{missive_type}/"
    return {"id": webhook_id, "type": missive_type, "url": url}


def _create(parsed, provider_name, provider, missive_type, resource) -> bool:
    if resource not in ("", "webhook"):
        print(f"Error: Unknown resource '{resource}'. Use: webhook", file=sys.stderr)
        return False
    if not missive_type:
        print("Error: --type required for webhook (e.g. email, sms)", file=sys.stderr)
        return False
    service = provider_service_name("create_webhook", missive_type)
    if not _supports(provider, service):
        return False
    result_id = provider.call_service(
        service,
        webhook_data=_webhook_data(parsed, provider_name, missive_type),
    )
    print_separator()
    print_header(f"{provider_name} - created webhook")
    print_separator()
    print(f"webhook_id={result_id}")
    return True


def _update(parsed, provider_name, provider, missive_type, resource) -> bool:
    if resource not in ("", "webhook"):
        print(f"Error: Unknown resource '{resource}'. Use: webhook", file=sys.stderr)
        return False
    webhook_id = parsed.get("webhook_id", "")
    if not webhook_id or not missive_type:
        print("Error: --webhook-id and --type required for webhook update", file=sys.stderr)
        return False
    service = provider_service_name("update_webhook", missive_type)
    if not _supports(provider, service):
        return False
    provider.call_service(
        service,
        webhook_data=_webhook_data(parsed, provider_name, missive_type, webhook_id),
    )
    print("Webhook updated.")
    return True


def _delete_sending(parsed, provider_name, provider, missive_type) -> bool:
    external_id = parsed.get("external_id", "")
    if not external_id:
        print("Error: --external-id required for delete missive", file=sys.stderr)
        return False
    missive_type = missive_type or "registered_letter"
    service = provider_service_name("delete", missive_type)
    if not _supports(provider, service):
        return False
    try:
        result = provider.call_service(service, external_id=external_id)
        _print_json_result(f"{provider_name} - deleted {missive_type} sending", result)
        return True
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False


def _delete_webhook(parsed, provider, missive_type) -> bool:
    webhook_id = parsed.get("webhook_id", "")
    if not webhook_id or not missive_type:
        print("Error: --webhook-id and --type required for webhook delete", file=sys.stderr)
        return False
    service = provider_service_name("delete_webhook", missive_type)
    if not _supports(provider, service):
        return False
    provider.call_service(service, webhook_data={"id": webhook_id, "type": missive_type})
    print("Webhook deleted.")
    return True


def _delete(parsed, provider_name, provider, missive_type, resource) -> bool:
    if resource in ("missive", "sending"):
        return _delete_sending(parsed, provider_name, provider, missive_type)
    if resource in ("", "webhook"):
        return _delete_webhook(parsed, provider, missive_type)
    print(f"Error: Unknown resource '{resource}'. Use: webhook, missive", file=sys.stderr)
    return False


def _retrieve_service(provider, service, **kwargs):
    if not _supports(provider, service):
        return False, None
    provider.call_service(service, **kwargs)
    return True, provider.get_service_normalize(service)


def _retrieve_period(parsed, provider, missive_type, kind):
    if not missive_type:
        examples = "email, sms, registered_letter" if kind == "events" else "registered_letter, email"
        print(f"Error: --type required for retrieve {kind} (e.g. {examples})", file=sys.stderr)
        return False, None
    start_date = parsed.get("start_date") or ""
    end_date = parsed.get("end_date") or ""
    if not start_date or not end_date:
        print(f"Error: --start-date and --end-date required for retrieve {kind}", file=sys.stderr)
        return False, None
    service = provider_service_name(f"retrieve_{kind}", missive_type)
    return _retrieve_service(provider, service, start_date=start_date, end_date=end_date)


def _retrieve_tracking(parsed, provider, missive_type):
    if not missive_type:
        print("Error: --type required for retrieve tracking_number (e.g. registered_letter)", file=sys.stderr)
        return False, None
    external_id = parsed.get("external_id", "")
    if not external_id:
        print("Error: --external-id required for retrieve tracking_number", file=sys.stderr)
        return False, None
    service = provider_service_name("tracking_number", missive_type)
    return _retrieve_service(provider, service, external_id=external_id)


def _retrieve_data(parsed, provider, missive_type, resource):
    simple_services = {
        "webhooks": "retrieve_webhooks",
        "email": "retrieve_email",
        "sms": "retrieve_sms",
    }
    if resource in simple_services:
        return _retrieve_service(provider, simple_services[resource])
    if resource in ("registered_letter", "letter"):
        return _retrieve_service(provider, provider_service_name("retrieve", resource))
    if resource == "events":
        return _retrieve_period(parsed, provider, missive_type, "events")
    if resource in ("billings", "billing"):
        return _retrieve_period(parsed, provider, missive_type, "billings")
    if resource == "tracking_number":
        return _retrieve_tracking(parsed, provider, missive_type)
    print(
        "Error: Use webhooks, email, registered_letter, letter, sms, events, billings, tracking_number "
        "(e.g. missive retrieve webhooks --provider X)",
        file=sys.stderr,
    )
    return False, None


def _retrieve(parsed, provider_name, provider, missive_type, resource) -> bool:
    resource = resource or "webhooks"
    success, data = _retrieve_data(parsed, provider, missive_type, resource)
    if not success:
        return False
    _print_json_result(f"{provider_name} - {resource}", data)
    return True


def _cancel(parsed, provider_name, provider, missive_type, resource) -> bool:
    external_id = parsed.get("external_id", "")
    if not external_id:
        print("Error: --external-id required for cancel", file=sys.stderr)
        return False
    missive_type = missive_type or "registered_letter"
    service = provider_service_name("cancel", missive_type)
    if not _supports(provider, service):
        return False
    try:
        result = provider.call_service(service, external_id=external_id)
        _print_json_result(f"{provider_name} - cancelled {missive_type}", result)
        return True
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return False


_SUBCOMMANDS = {
    "create": _create,
    "retrieve": _retrieve,
    "send": _send,
    "update": _update,
    "delete": _delete,
    "cancel": _cancel,
}


def _missive_command(args: list[str]) -> bool:
    args = [f"--{arg[2:].replace('-', '_')}" if arg.startswith("--") else arg for arg in args]
    parsed = parse_args_from_config(args, _ARG_CONFIG, prog="missive")
    if parsed.get("help"):
        from .help import print_command_help

        return print_command_help("missive")
    cmd_args = parsed.get("args") or []
    subcommand = cmd_args[0] if cmd_args else ""
    handler = _SUBCOMMANDS.get(subcommand)
    if handler is None:
        print("Error: Use create, retrieve, send, update, delete, cancel", file=sys.stderr)
        return False
    provider_result = _get_provider(parsed)
    if not provider_result:
        return False
    provider_name, provider = provider_result
    missive_type = parsed.get("type") or parsed.get("missive_type", "")
    resource = cmd_args[1] if len(cmd_args) > 1 else ""
    return handler(parsed, provider_name, provider, missive_type, resource)


missive_command = Command(
    _missive_command,
    "Missive: create, retrieve, send, update, delete (webhook/missive), cancel (missive send --provider X --missive-type email --recipients '[...]')",
)

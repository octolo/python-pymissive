"""Billing handling: fetch via provider.get_billings_{missive_type}, then process each billing."""

import csv
from collections import OrderedDict
from decimal import Decimal
from io import StringIO

from django.db.models.manager import Manager
from django.db.models.query import QuerySet
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _

from .models.billing import MissiveBilling
from .models.missive import Missive
from .retrieve import lookup_missive
from .utils import get_base_url, get_recipient


def _process_billing(missive, bill):
    """Upsert one provider billing line.

    Identity is missive + invoice + recipient. Amounts stay in ``defaults`` so
    a corrected total updates the row instead of inserting a second one that
    ``total_billing_amount`` would sum.
    """
    lookup = {
        "missive": missive,
        "invoice": bill.get("invoice") or None,
        "recipient": (
            get_recipient(missive, bill["recipient"]) if bill.get("recipient") else None
        ),
    }
    defaults = {
        "billing_amount": bill.get("billing_amount"),
        "estimate_amount": bill.get("estimate_amount"),
        "currency": bill.get("currency"),
        "trace": bill.get("raw") or {},
    }
    MissiveBilling.objects.update_or_create(defaults=defaults, **lookup)


def _lookup_billing_missive(bill) -> Missive | None:
    missive = lookup_missive(partner_id=bill.get("external_id"))
    if missive is not None:
        return missive
    return lookup_missive(
        uid=bill.get("substitute_id") or bill.get("user_reference")
    )


def handle_billings(**kwargs) -> None:
    """Fetch billings from provider and process each one."""
    from .models.provider import MissiveProviderModel

    provider = kwargs.get("provider")
    provider = MissiveProviderModel.objects.get(name=provider)
    service_name = f"get_billings_{kwargs.get('missive_type')}"
    if not hasattr(provider._provider, service_name):
        return
    billings = provider._provider.call_service_formatted(service_name, **kwargs)
    if not billings:
        return
    missive = Missive.objects.get_by_external_id(kwargs.get("external_id"))
    if missive is None:
        return
    for bill in billings:
        _process_billing(missive, bill)


def retrieve_billings(*, provider, missive_type, start_date, end_date):
    """Fetch billings from the provider between two dates, then store them."""
    from django.core.exceptions import ValidationError
    from django.utils.translation import gettext_lazy as _

    from .models.provider import MissiveProviderModel

    provider_obj = MissiveProviderModel.objects.get(name=str(provider))
    service = f"retrieve_billings_{missive_type}"
    if not hasattr(provider_obj._provider, service):
        raise ValidationError(
            _("This provider does not support billings for this missive type.")
        )
    raw = provider_obj._provider.call_service(
        service, start_date=start_date, end_date=end_date
    )
    if isinstance(raw, dict):
        raw = raw.get("billings") or raw.get("items") or raw
    if not isinstance(raw, list):
        return
    for bill in raw:
        if not isinstance(bill, dict):
            continue
        missive = _lookup_billing_missive(bill)
        if missive is None:
            continue
        _process_billing(missive, bill)


def delay_retrieve_billings(*, provider, missive_type, start_date, end_date):
    """Dispatch :func:`retrieve_billings` via the configured task backend."""
    from .task import get_task_backend

    get_task_backend().enqueue(
        retrieve_billings,
        provider=str(provider),
        missive_type=missive_type,
        start_date=start_date,
        end_date=end_date,
    )


def _format_address(address) -> str:
    if not address:
        return ""
    if isinstance(address, str):
        return address
    if hasattr(address, "get"):
        parts = [
            address.get("address_line1"),
            address.get("address_line2"),
            address.get("postal_code"),
            address.get("city"),
            address.get("country"),
        ]
        return ", ".join(str(part) for part in parts if part)
    return str(address)


def _csv_value(value) -> str:
    if value is None:
        return ""
    return str(value)


def billings_export_queryset(*, start_date, end_date, provider=None, missive_type=None):
    """Billings whose ``created_at`` falls in ``[start_date, end_date]``."""
    qs = MissiveBilling.objects.select_related(
        "missive", "missive__campaign", "recipient"
    ).prefetch_related(
        "missive__to_missiverelatedobject__content_type",
        "missive__campaign__to_campaignrelatedobject__content_type",
    ).filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )
    if provider:
        qs = qs.filter(missive__provider=str(provider))
    if missive_type:
        qs = qs.filter(missive__missive_type=missive_type)
    return qs.order_by("created_at", "pk")


def mark_billings_billed(*, start_date, end_date, provider=None, missive_type=None) -> int:
    """Set ``is_billed`` on billings with an amount in the date range."""
    return (
        billings_export_queryset(
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            missive_type=missive_type,
        )
        .filter(billing_amount__gt=0)
        .update(is_billed=True)
    )


def _collect_live_related(manager, into: dict, seen: set) -> None:
    """Group live related objects by content type; skip deleted; dedup via ``seen``."""
    for related in manager.all():
        obj = related.content_object
        if obj is None:
            continue
        ct_name = related.content_type.model
        key = (ct_name, obj.pk)
        if key in seen:
            continue
        seen.add(key)
        into.setdefault(ct_name, []).append(obj)


def related_objects_by_content_type(missive) -> dict:
    """Missive ∪ campaign related objects, missive first (same order as template context)."""
    grouped: dict[str, list] = {}
    seen: set[tuple[str, object]] = set()
    _collect_live_related(missive.to_missiverelatedobject, into=grouped, seen=seen)
    if getattr(missive, "campaign_id", None):
        _collect_live_related(
            missive.campaign.to_campaignrelatedobject, into=grouped, seen=seen
        )
    return grouped


def _resolve_related_attr(obj, name: str):
    if obj is None or not name or name.startswith("_"):
        return None
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    if callable(value) or isinstance(value, (Manager, QuerySet)):
        return None
    return value


def _resolve_attrs(obj, names: list[str]):
    current = obj
    for name in names:
        current = _resolve_related_attr(current, name)
        if current is None:
            return ""
    return current


def _path_content_type(path: str) -> str:
    return str(path).split(".", 1)[0]


def extra_field_widths(grouped_list: list[dict], extra_fields: list[str]) -> dict[str, int]:
    """Max related-object count per content type (at least 1 column per path)."""
    widths: dict[str, int] = {}
    for path in extra_fields:
        ct = _path_content_type(path)
        widths[ct] = 1
    for grouped in grouped_list:
        for ct in widths:
            widths[ct] = max(widths[ct], len(grouped.get(ct) or []))
    return widths


def extra_field_headers(extra_fields: list[str], widths: dict[str, int]) -> list[str]:
    headers = []
    for path in extra_fields:
        n = widths.get(_path_content_type(path), 1)
        headers.extend(f"{path}.{i}" for i in range(1, n + 1))
    return headers


def extra_field_values(grouped: dict, extra_fields: list[str], widths: dict[str, int]) -> list[str]:
    values = []
    for path in extra_fields:
        parts = [part for part in str(path).split(".") if part]
        ct = parts[0] if parts else ""
        rest = parts[1:]
        objects = grouped.get(ct) or []
        n = widths.get(ct, 1)
        for i in range(n):
            if i < len(objects) and rest:
                values.append(_csv_value(_resolve_attrs(objects[i], rest)))
            else:
                values.append("")
    return values


def _missive_admin_url(missive) -> str:
    if not getattr(missive, "pk", None):
        return ""
    try:
        path = reverse("admin:django_pymissive_missive_change", args=[missive.pk])
    except NoReverseMatch:
        return ""
    return get_base_url(trailing_slash=False) + path


def _invoice_label(billing) -> str:
    return (billing.invoice or "").strip() or _("Untitled")


def _missive_identity_row(billing, *, recipient=None) -> list[str]:
    missive = billing.missive
    if recipient is None:
        recipient = billing.recipient
    created = billing.created_at
    created_value = created.isoformat(timespec="seconds") if created else ""
    return [
        created_value,
        _csv_value(missive.pk if missive else ""),
        _csv_value(_missive_admin_url(missive)),
        _csv_value(getattr(missive, "external_id", None)),
        _csv_value(getattr(missive, "substitute_id", None)),
        _csv_value(getattr(missive, "subject", None)),
        _csv_value(getattr(missive, "provider", None)),
        _csv_value(getattr(missive, "missive_type", None)),
        _csv_value(recipient.name if recipient else ""),
        _csv_value(getattr(recipient, "email", None) if recipient else ""),
        _csv_value(getattr(recipient, "phone", None) if recipient else ""),
        _format_address(getattr(recipient, "address", None) if recipient else None),
    ]


def _billing_base_row(billing) -> list[str]:
    return [
        *_missive_identity_row(billing),
        _csv_value(billing.billing_amount),
        _csv_value(billing.estimate_amount),
        _csv_value(billing.currency),
        "1" if billing.is_billed else "0",
        _csv_value(billing.invoice),
    ]


def _group_billings_by_missive(billings) -> list[list]:
    groups: OrderedDict = OrderedDict()
    for billing in billings:
        groups.setdefault(billing.missive_id, []).append(billing)
    return list(groups.values())


def _invoice_labels(billings) -> list[str]:
    labels = []
    seen = set()
    for billing in billings:
        label = _invoice_label(billing)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _amounts_by_invoice(group) -> dict:
    amounts: dict[str, Decimal | None] = {}
    for billing in group:
        label = _invoice_label(billing)
        amount = billing.billing_amount
        if amount is None:
            amounts.setdefault(label, None)
            continue
        current = amounts.get(label)
        amounts[label] = amount if current is None else current + amount
    return amounts


def _pivot_identity_row(group) -> list[str]:
    first = group[0]
    with_recipient = next((billing for billing in group if billing.recipient_id), first)
    currency = next((billing.currency for billing in group if billing.currency), "")
    billed = all(billing.is_billed for billing in group)
    row = _missive_identity_row(first, recipient=with_recipient.recipient)
    row.extend(
        [
            _csv_value(currency),
            "1" if billed else "0",
        ]
    )
    return row


def _extra_columns(billings, extra_fields):
    grouped_list = [
        related_objects_by_content_type(billing.missive) if billing.missive else {}
        for billing in billings
    ]
    widths = extra_field_widths(grouped_list, extra_fields) if extra_fields else {}
    return grouped_list, widths


def render_billings_csv(queryset, extra_fields=None, one_row=False) -> str:
    """CSV text (UTF-8) for the given billing queryset."""
    extra_fields = list(extra_fields or [])
    billings = list(queryset)
    if one_row:
        groups = _group_billings_by_missive(billings)
        representatives = [group[0] for group in groups]
        grouped_list, widths = _extra_columns(representatives, extra_fields)
        labels = _invoice_labels(billings)
        headers = [
            _("Created At"),
            _("Missive"),
            _("Admin"),
            _("External ID"),
            _("Substitute ID"),
            _("Subject"),
            _("Provider"),
            _("Missive type"),
            _("Recipient"),
            _("Recipient Email"),
            _("Phone"),
            _("Address"),
            _("Currency"),
            _("Billed"),
            *labels,
            *extra_field_headers(extra_fields, widths),
        ]
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        for group, grouped in zip(groups, grouped_list):
            amounts = _amounts_by_invoice(group)
            row = _pivot_identity_row(group)
            row.extend(_csv_value(amounts.get(label)) for label in labels)
            if extra_fields:
                row.extend(extra_field_values(grouped, extra_fields, widths))
            writer.writerow(row)
        return buffer.getvalue()

    grouped_list, widths = _extra_columns(billings, extra_fields)
    headers = [
        _("Created At"),
        _("Missive"),
        _("Admin"),
        _("External ID"),
        _("Substitute ID"),
        _("Subject"),
        _("Provider"),
        _("Missive type"),
        _("Recipient"),
        _("Recipient Email"),
        _("Phone"),
        _("Address"),
        _("Billing Amount"),
        _("Estimate Amount"),
        _("Currency"),
        _("Billed"),
        _("Invoice"),
        *extra_field_headers(extra_fields, widths),
    ]
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for billing, grouped in zip(billings, grouped_list):
        row = _billing_base_row(billing)
        if extra_fields:
            row.extend(extra_field_values(grouped, extra_fields, widths))
        writer.writerow(row)
    return buffer.getvalue()

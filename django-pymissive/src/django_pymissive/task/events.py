from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models.event import MissiveEvent
from ..models.missive import Missive
from ..models.recipient import MissiveRecipient
from ..models.choices import MissiveRecipientType


def _get_occurred_at(occurred_at):
    """Parse occurred_at to timezone-aware datetime."""
    if isinstance(occurred_at, str):
        occurred_at = parse_datetime(occurred_at.replace("Z", "+00:00"))
    if occurred_at is not None and timezone.is_naive(occurred_at):
        return timezone.make_aware(occurred_at, dt_timezone.utc)
    if occurred_at is None:
        return timezone.now()
    return occurred_at


def _get_recipient(missive, event: dict) -> MissiveRecipient | None:
    """Get recipient from normalized event, or None if not present."""
    # Support flat fields, nested "recipient", or "recipients" list (use first)
    recipient = event.get("recipient")
    recipients = event.get("recipients")
    if isinstance(recipients, list) and recipients:
        recipient = recipients[0] if isinstance(recipients[0], dict) else None
    data = {**(recipient or {}), **event} if isinstance(recipient, dict) else event
    for field in ["email", "phone", "address", "notification_id"]:
        val = data.get(field)
        if val is not None:
            return MissiveRecipient.objects.filter(
                missive=missive,
                **{field: val},
                recipient_type__in=[
                    MissiveRecipientType.RECIPIENT,
                    MissiveRecipientType.CC,
                    MissiveRecipientType.BCC,
                ],
            ).first()
    if data.get("internal_id") is not None:
        return MissiveRecipient.objects.filter(missive=missive, id=data["internal_id"]).first()
    return None


def _update_recipient_timestamps(recipient, event_type: str, occurred_at) -> None:
    """Update recipient sent_at/delivered_at from event."""
    if not recipient or not occurred_at:
        return
    event_type = (event_type or "").lower()
    if event_type == "sent" and not recipient.sent_at:
        recipient.sent_at = occurred_at
        recipient.save(update_fields=["sent_at"])
    elif event_type == "delivered" and not recipient.delivered_at:
        recipient.delivered_at = occurred_at
        recipient.save(update_fields=["delivered_at"])


def _save_untreated_event(provider: str, event: dict, reason: str = "") -> None:
    """Save an event that could not be fully processed for later correction."""
    occurred_at = _get_occurred_at(event.get("occurred_at"))
    trace = event.get("raw") or event.get("trace") or {}
    if reason:
        trace["_untreated_reason"] = reason
    MissiveEvent.objects.create(
        missive=None,
        recipient=None,
        provider=provider,
        event="untreated",
        description=reason or event.get("description", "Could not process event"),
        occurred_at=occurred_at,
        trace=trace,
    )


def _process_event(event: dict, provider: str = None) -> tuple[Missive | None, MissiveRecipient | None]:
    """Process a single normalized event. Returns (missive, recipient)."""
    external_id = event.get("external_id") or event.get("id")
    resource_custom_id = event.get("resource_custom_id")
    if not external_id and not resource_custom_id:
        _save_untreated_event(provider or "", event, "Missing external_id and resource_custom_id")
        return None, None

    missive = None
    if external_id:
        missive = Missive.objects.filter(external_id=external_id).first()
    if not missive and resource_custom_id:
        missive = Missive.objects.filter(pk=resource_custom_id).first()
    if not missive:
        _save_untreated_event(
            provider or "", event,
            f"Missive not found: external_id={external_id!r}, resource_custom_id={resource_custom_id!r}"
        )
        return None, None

    try:
        recipient = _get_recipient(missive, event)

        recipient_id = event.get("recipient_id")
        if not recipient_id and isinstance(event.get("recipients"), list) and event["recipients"]:
            first = event["recipients"][0]
            recipient_id = first.get("external_id") if isinstance(first, dict) else None
        if recipient and recipient_id and not recipient.external_id:
            recipient.external_id = recipient_id
            recipient.save(update_fields=["external_id"])

        occurred_at = _get_occurred_at(event.get("occurred_at"))
        data = {
            "missive": missive,
            "recipient": recipient,
            "provider": provider,
            "event": event.get("event"),
            "description": event.get("description"),
            "occurred_at": occurred_at,
            "trace": event.get("raw") or event.get("trace") or {},
        }
        if event.get("user_action"):
            data.update({
                "user_action": event.get("user_action", False),
                "billing_amount": event.get("billing_amount"),
                "estimate_amount": event.get("estimate_amount"),
                "is_billed": event.get("is_billed") or False,
            })

        pk = event.get("pk")
        if pk:
            MissiveEvent.objects.update_or_create(pk=pk, defaults=data)
        else:
            MissiveEvent.objects.get_or_create(**data)

        _update_recipient_timestamps(recipient, event.get("event"), occurred_at)
        return missive, recipient
    except Exception as e:
        _save_untreated_event(provider or "", event, str(e))
        return None, None


def handle_events(events: list[dict] | dict, provider: str = None) -> Missive | None:
    """Handle normalized webhook events. Returns last missive for compatibility."""
    if isinstance(events, dict):
        events = [events]

    last_missive = None
    recipients_seen = set()

    for event in events:
        missive, recipient = _process_event(event, provider)
        last_missive = missive
        if recipient and recipient.pk not in recipients_seen:
            recipients_seen.add(recipient.pk)
            recipient.set_last_status()

    if last_missive:
        last_missive.set_last_status()

    return last_missive
    
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models.event import MissiveEvent
from ..models.missive import Missive
from ..models.recipient import MissiveRecipient
from ..models.choices import MissiveRecipientType


def _get_occurred_at(occurred_at):
    """Get occurred at from normalized event."""
    if isinstance(occurred_at, str):
        occurred_at = parse_datetime(occurred_at.replace("Z", "+00:00"))
    if occurred_at is not None and timezone.is_naive(occurred_at):
        return timezone.make_aware(occurred_at, dt_timezone.utc)
    if occurred_at is None:
        return timezone.now()
    return occurred_at

def get_recipient_data(normalized):
    """Get recipient data from normalized event."""
    data = {}
    for field in ["email", "phone", "address", "notification_id"]:
        if normalized.get(field) and normalized[field] is not None:
            return {field: normalized[field]}
    return data

def _process_normalized_event_recipient(missive, normalized):
    """Process normalized webhook event recipient."""
    recipient_data = get_recipient_data(normalized)
    recipient = None
    if recipient_data:
        recipient = MissiveRecipient.objects.get(
            **recipient_data,
            missive=missive,
            recipient_type__in=[
                MissiveRecipientType.RECIPIENT,
                MissiveRecipientType.CC,
                MissiveRecipientType.BCC,
            ],
        )
    return recipient

def _process_normalized_event(normalized):
    """Process normalized webhook event and update missive/recipient status."""
    missive = Missive.objects.get(external_id=normalized["external_id"])
    recipient = _process_normalized_event_recipient(missive, normalized)
    occurred_at = _get_occurred_at(normalized.get("occurred_at"))
    data_event = {
        "missive": missive,
        "recipient": recipient,
        "event": normalized["event"],
        "description": normalized["description"],
        "occurred_at": occurred_at,
        "trace": normalized["raw"],
    }

    if normalized.get("user_action"):
        data_event.update({
            "user_action": normalized.get("user_action", False),
            "billing_amount": normalized.get("billing_amount"),
            "estimate_amount": normalized.get("estimate_amount"),
            "is_billed": normalized.get("is_billed") or False,
        })

    if normalized.get("pk"):
        MissiveEvent.objects.update_or_create(pk=normalized["pk"], defaults=data_event)
    else:
        MissiveEvent.objects.get_or_create(**data_event)
    return missive, recipient


def _update_recipient_timestamps(recipient, event_type: str, occurred_at):
    """Update recipient sent_at/delivered_at from event."""
    if not recipient:
        return
    event_type = (event_type or "").lower()
    if event_type == "sent" and not recipient.sent_at:
        recipient.sent_at = occurred_at
        recipient.save(update_fields=["sent_at"])
    elif event_type == "delivered" and not recipient.delivered_at:
        recipient.delivered_at = occurred_at
        recipient.save(update_fields=["delivered_at"])


def handle_events(events: list[dict] | dict):
    """Handle events."""
    if isinstance(events, dict):
        events = [events]
    missive = None
    recipients = []
    for event in events:
        missive, recipient = _process_normalized_event(event)
        if recipient and recipient not in recipients:
            recipients.append(recipient)
        occurred_at = _get_occurred_at(event.get("occurred_at"))
        _update_recipient_timestamps(recipient, event.get("event"), occurred_at)
    if missive:
        missive.set_last_status()
    for recipient in recipients:
        recipient.set_last_status()

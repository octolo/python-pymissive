"""Event handling: normalize via provider.handle_webhook_{missive_type}, then process each event."""

from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models.choices import MissiveEventType
from .models.event import MissiveEvent
from .models.missive import Missive
from .utils import get_recipient


def _can_save_untreated(provider_name):
    CONF_SAVE_UNTREATED = getattr(settings, "PYMISSIVE_SAVE_UNTREATED_EVENTS", False)
    if CONF_SAVE_UNTREATED is True:
        return True
    if isinstance(CONF_SAVE_UNTREATED, list):
        return provider_name in CONF_SAVE_UNTREATED
    return False


def _get_occurred_at(occurred_at):
    if isinstance(occurred_at, str):
        occurred_at = parse_datetime(occurred_at.replace("Z", "+00:00"))
    if occurred_at is not None and timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at, dt_timezone.utc)
    if occurred_at is not None:
        return occurred_at.replace(microsecond=0)
    return timezone.now().replace(microsecond=0)


def _save_untreated(event, provider):
    provider_name = getattr(provider, "name", None) or str(provider)
    if not _can_save_untreated(provider_name):
        return
    trace = {"event": event, "provider": provider_name}
    MissiveEvent.objects.create(
        missive=None,
        recipient=None,
        event=MissiveEventType.ERROR,
        reason=event.get("reason", "Could not process event"),
        occurred_at=_get_occurred_at(event.get("occurred_at")),
        trace=trace,
    )


# Sending-level lifecycle events that describe the whole missive rather than a
# single recipient. Some providers (e.g. Maileva LRE) emit them without any
# recipient attached; status is derived from the latest event of each
# *recipient*, so a recipient-less event would be ignored and the missive would
# stay ``DRAFT``. We fan these out to every recipient instead. Only early
# lifecycle events are fanned out: terminal/per-recipient events (delivered,
# undelivered, archived, proofs, ...) always carry their own recipient.
FANOUT_EVENTS = {"request", "accepted", "processed", "queued", "processing"}


def _upsert_event(event, missive, recipient, occurred_at, allow_pk=True):
    lookup = {
        "missive": missive,
        "event": event.get("event"),
        "occurred_at": occurred_at,
    }
    if recipient is not None:
        lookup["recipient"] = recipient
    defaults = {
        "reason": event.get("reason", "No reason provided"),
        "trace": event.get("raw") or {},
    }
    raw = event.get("raw") or {}
    if allow_pk and "pk" in raw:
        defaults = {
            **defaults,
            **lookup,
        }
        lookup = {"pk": raw.get("pk")}
    MissiveEvent.objects.update_or_create(defaults=defaults, **lookup)


def _process_event(event, missive):
    occurred_at = _get_occurred_at(event.get("occurred_at"))

    if event.get("recipient"):
        recipient = get_recipient(missive, event.get("recipient"))
        _upsert_event(event, missive, recipient, occurred_at)
        if recipient:
            recipient.set_status()
        missive.set_status()
        return

    fanout_recipients = (
        list(missive.recipients) if event.get("event") in FANOUT_EVENTS else []
    )
    if fanout_recipients:
        for recipient in fanout_recipients:
            _upsert_event(event, missive, recipient, occurred_at, allow_pk=False)
            recipient.set_status()
    else:
        _upsert_event(event, missive, None, occurred_at)
    missive.set_status()


def handle_event(event, provider, missive_type: str) -> Missive | None:
    try:
        external_id = event.get("external_id")
        missive = Missive.objects.get(external_id=external_id)
        _process_event(event, missive)
    except Missive.DoesNotExist:
        _save_untreated(event, provider)
    return None


def handle_events(events, provider, missive_type: str) -> Missive | None:
    """Normalize via provider.handle_webhook_{missive_type}, then process each event."""
    events_normalized = provider._provider.call_service_formatted(
        f"handle_webhook_{missive_type}", payload=events
    )
    if events_normalized:
        if isinstance(events_normalized, dict):
            events_normalized = [events_normalized]
        for event in events_normalized:
            handle_event(event, provider, missive_type)
    return None


def retrieve_events(*, provider, missive_type, start_date, end_date):
    """Fetch events from the provider between two dates, then handle them."""
    from django.core.exceptions import ValidationError
    from django.utils.translation import gettext_lazy as _

    from .models.provider import MissiveProviderModel

    provider_obj = MissiveProviderModel.objects.get(name=str(provider))
    service = f"events_{missive_type}"
    if not hasattr(provider_obj._provider, service):
        raise ValidationError(
            _("This provider does not support events for this missive type.")
        )
    raw = provider_obj._provider.call_service(
        service, start_date=start_date, end_date=end_date
    )
    if isinstance(raw, dict):
        raw = raw.get("events") or raw
    handle_events(raw, provider_obj, missive_type)


def delay_retrieve_events(*, provider, missive_type, start_date, end_date):
    """Dispatch :func:`retrieve_events` via the configured task backend."""
    from .task import get_task_backend

    get_task_backend().enqueue(
        retrieve_events,
        provider=str(provider),
        missive_type=missive_type,
        start_date=start_date,
        end_date=end_date,
    )

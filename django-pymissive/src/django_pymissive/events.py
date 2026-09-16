"""Event handling: normalize via provider.handle_webhook_{missive_type}, then process each event."""

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from pymissive.config import provider_service_name

from .models.choices import MissiveEventType
from .models.event import MissiveEvent
from .models.missive import Missive
from .signals import suppress_event_billings, trigger_billings
from .utils import get_recipient

logger = logging.getLogger(__name__)

#: Stable stand-in when the provider omits ``occurred_at``. ``timezone.now()``
#: would change on every retry and create a new row. A real timestamp is never
#: 1970, so this cannot collide with a dated event. Truthy so ``MissiveEvent.save``
#: does not replace it with ``now()``.
UNKNOWN_OCCURRED_AT = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


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
    return UNKNOWN_OCCURRED_AT


def _save_untreated(event, provider) -> bool:
    """Park an event whose missive is unknown. False when it was dropped."""
    provider_name = getattr(provider, "name", None) or str(provider)
    if not _can_save_untreated(provider_name):
        return False
    trace = {"event": event, "provider": provider_name}
    MissiveEvent.objects.create(
        missive=None,
        recipient=None,
        event=MissiveEventType.ERROR,
        reason=event.get("reason", "Could not process event"),
        occurred_at=_get_occurred_at(event.get("occurred_at")),
        trace=trace,
    )
    return True


# Sending-level lifecycle events that describe the whole missive rather than a
# single recipient. Some providers (e.g. Maileva registered letter) emit them without any
# recipient attached; status is derived from the latest event of each
# *recipient*, so a recipient-less event would be ignored and the missive would
# stay ``DRAFT``. We fan these out to every recipient instead. Only early
# lifecycle events are fanned out: terminal/per-recipient events (delivered,
# undelivered, archived, proofs, ...) always carry their own recipient.
FANOUT_EVENTS = {"request", "accepted", "processed", "queued", "processing"}


def _upsert_event(event, missive, recipient, occurred_at, pk=None):
    """Create or update the event row identified by its business key.

    The business key is ``(missive, event, occurred_at, recipient)``.
    ``recipient`` is always in the lookup, including ``None``, so a
    sending-level row does not match fanned-out per-recipient rows.

    ``pk`` targets one existing row instead, so a replay updates the row it
    came from rather than duplicating it — the business key then moves to the
    values written. It is a caller argument on purpose: it must never be read
    from the event payload, since ``raw`` is the provider request body verbatim
    and ``MissiveEvent`` has a sequential pk, which would let an unauthenticated
    webhook rewrite any event row by guessing its id.
    """
    business_key = {
        "missive": missive,
        "event": event.get("event"),
        "occurred_at": occurred_at,
        "recipient": recipient,
    }
    lookup = dict(business_key)
    defaults = {
        "reason": event.get("reason", "No reason provided"),
        "trace": event.get("raw") or {},
    }
    if pk is not None:
        defaults = {
            **defaults,
            **lookup,
        }
        lookup = {"pk": pk}
    try:
        with transaction.atomic():
            MissiveEvent.objects.update_or_create(defaults=defaults, **lookup)
    except (MultipleObjectsReturned, IntegrityError):
        # Pre-constraint duplicates, or a lost insert race against the unique
        # index. Replay (pk lookup) may also collide with the business key.
        row = (
            MissiveEvent.objects.filter(**lookup).order_by("pk").first()
            or MissiveEvent.objects.filter(**business_key).order_by("pk").first()
        )
        if row is None:
            raise
        for key, value in defaults.items():
            setattr(row, key, value)
        row.save(update_fields=list(defaults))


def _process_event(event, missive, pk=None):
    occurred_at = _get_occurred_at(event.get("occurred_at"))

    if event.get("recipient"):
        recipient = get_recipient(missive, event.get("recipient"))
        _upsert_event(event, missive, recipient, occurred_at, pk=pk)
        if recipient:
            recipient.set_status()
        missive.set_status()
        return

    fanout_recipients = (
        list(missive.recipients) if event.get("event") in FANOUT_EVENTS else []
    )
    if fanout_recipients:
        # No pk here: one row per recipient, so there is no single row to target.
        # The rows all belong to the same missive, so the per-event billing
        # signal is suppressed and the provider is called once below instead of
        # once per recipient — a 50-recipient webhook used to mean 50 calls.
        with suppress_event_billings():
            for recipient in fanout_recipients:
                _upsert_event(event, missive, recipient, occurred_at)
                recipient.set_status()
        trigger_billings(missive)
    else:
        _upsert_event(event, missive, None, occurred_at, pk=pk)
    missive.set_status()


def handle_event(event, provider, missive_type: str) -> bool:
    """Process one event. False when it could be neither applied nor parked.

    An unknown ``external_id`` is usually a webhook that overtook the commit of
    the missive it refers to, so losing it is not acceptable: the caller turns
    a False into a retryable response.
    """
    missive = Missive.objects.get_by_external_id(event.get("external_id"))
    if missive is None:
        return _save_untreated(event, provider)
    _process_event(event, missive)
    return True


def handle_events(events, provider, missive_type: str) -> int:
    """Normalize via provider.handle_webhook_{missive_type}, then process each event.

    Returns the number of events that were lost. One bad event must not stop
    the batch, but the count lets the webhook answer with a retryable status
    instead of pretending everything went through.
    """
    events_normalized = provider._provider.call_service_formatted(
        provider_service_name("handle_webhook", missive_type), payload=events
    )
    if not events_normalized:
        return 0
    if isinstance(events_normalized, dict):
        events_normalized = [events_normalized]
    lost = 0
    for event in events_normalized:
        try:
            if not handle_event(event, provider, missive_type):
                lost += 1
                logger.warning(
                    "handle_events: no missive for external_id=%s event=%s",
                    event.get("external_id") if isinstance(event, dict) else None,
                    event.get("event") if isinstance(event, dict) else None,
                )
        except Exception:
            lost += 1
            logger.exception(
                "handle_events: failed for external_id=%s event=%s",
                event.get("external_id") if isinstance(event, dict) else None,
                event.get("event") if isinstance(event, dict) else None,
            )
    return lost


def retrieve_events(*, provider, missive_type, start_date, end_date):
    """Fetch events from the provider between two dates, then handle them."""
    from django.core.exceptions import ValidationError
    from django.utils.translation import gettext_lazy as _

    from .models.provider import MissiveProviderModel

    provider_obj = MissiveProviderModel.objects.get(name=str(provider))
    service = provider_service_name("retrieve_events", missive_type)
    if not hasattr(provider_obj._provider, service):
        raise ValidationError(
            _("This provider does not support events for this missive type.")
        )
    raw = provider_obj._provider.call_service(
        service, start_date=start_date, end_date=end_date
    )
    if isinstance(raw, dict):
        raw = raw.get("events") or raw
    from .signals import suppress_event_billings

    with suppress_event_billings():
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

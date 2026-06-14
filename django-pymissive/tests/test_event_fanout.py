"""Tests for sending-level webhook events fanned out to recipients.

Some providers (e.g. Maileva LRE) emit lifecycle webhooks at the *sending*
level, with no recipient attached (``resource_name == "sendings"``). Status is
derived from the latest event of each *recipient*, so a recipient-less event is
ignored by ``get_event_counts`` and the missive would stay ``DRAFT``.

``_process_event`` fans those lifecycle events out to every recipient so the
status leaves ``DRAFT``. Terminal/per-recipient events keep their own recipient
and are never fanned out.
"""

from __future__ import annotations

import pytest

from django_pymissive.events import _process_event
from django_pymissive.models import (
    MissiveEvent,
    MissiveRecipientEmail,
    MissiveStatus,
    MissiveType,
)
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive_with_recipients(n=2):
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Sujet",
        body_text="Corps du message.",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
        external_id="416e9b28-96fe-4f4c-a685-601ccf8eb1fc",
    )
    recipients = [
        MissiveRecipientEmail.objects.create(
            missive=missive,
            name=f"Recipient {i}",
            email=f"recipient{i}@example.com",
        )
        for i in range(n)
    ]
    return missive, recipients


def _event(event, **extra):
    return {
        "event": event,
        "occurred_at": "2026-06-12T09:30:16.417Z",
        "raw": {"resource_name": "sendings", **extra},
    }


def test_sending_level_event_fans_out_to_all_recipients():
    missive, recipients = _missive_with_recipients(2)

    _process_event(_event("accepted"), missive)

    for recipient in recipients:
        assert MissiveEvent.objects.filter(
            missive=missive, recipient=recipient, event="accepted"
        ).exists()
    # No recipient-less duplicate is created when we fan out.
    assert not MissiveEvent.objects.filter(
        missive=missive, recipient__isnull=True
    ).exists()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING


def test_processed_after_accepted_stays_processing():
    missive, recipients = _missive_with_recipients(2)

    _process_event(
        {"event": "accepted", "occurred_at": "2026-06-12T09:30:16Z", "raw": {}},
        missive,
    )
    _process_event(
        {"event": "processed", "occurred_at": "2026-06-12T11:30:41Z", "raw": {}},
        missive,
    )

    for recipient in recipients:
        recipient.refresh_from_db()
        assert recipient.status == MissiveStatus.PROCESSING
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING


def test_non_lifecycle_recipientless_event_is_not_fanned_out():
    missive, recipients = _missive_with_recipients(2)

    _process_event(_event("archived"), missive)

    # Stored once, recipient-less, so it does not drive recipient status.
    assert MissiveEvent.objects.filter(
        missive=missive, recipient__isnull=True, event="archived"
    ).count() == 1
    assert not MissiveEvent.objects.filter(
        missive=missive, recipient__isnull=False
    ).exists()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.DRAFT


def test_recipient_scoped_event_attaches_directly():
    missive, recipients = _missive_with_recipients(2)
    target = recipients[0]

    _process_event(
        {
            "event": "delivered",
            "occurred_at": "2026-06-12T12:00:00Z",
            "recipient": {"id": str(target.id)},
            "raw": {"resource_name": "recipients"},
        },
        missive,
    )

    assert MissiveEvent.objects.filter(
        missive=missive, recipient=target, event="delivered"
    ).exists()
    # Not propagated to the other recipient.
    assert not MissiveEvent.objects.filter(
        missive=missive, recipient=recipients[1]
    ).exists()

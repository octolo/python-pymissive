"""A fanned-out webhook must bill once per missive, not once per recipient.

``trigger_billings_on_event`` is a ``post_save`` receiver, and a sending-level
event creates one row per recipient — all for the same missive. A 50-recipient
webhook therefore made 50 identical provider billing calls inside the request.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.billings import fetch_missive_billings
from django_pymissive.events import _process_event
from django_pymissive.models import MissiveEvent, MissiveRecipientEmail, MissiveStatus, MissiveType
from django_pymissive.models.choices import MissiveEventType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive_with_recipients(count):
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Sujet",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
        external_id="416e9b28-96fe-4f4c-a685-601ccf8eb1fc",
    )
    for index in range(count):
        MissiveRecipientEmail.objects.create(
            missive=missive,
            name=f"Recipient {index}",
            email=f"recipient{index}@example.com",
        )
    return missive


def _accepted_event():
    return {
        "event": "accepted",
        "occurred_at": "2026-06-12T09:30:16Z",
        "raw": {"resource_name": "sendings"},
    }


def test_a_fanned_out_event_bills_once_for_ten_recipients():
    missive = _missive_with_recipients(10)

    with patch.object(Missive, "can_billings", return_value=True), patch.object(
        Missive, "get_billings"
    ) as get_billings:
        _process_event(_accepted_event(), missive)

    assert get_billings.call_count == 1


def test_a_recipient_scoped_event_still_bills_once():
    missive = _missive_with_recipients(3)
    target = missive.recipients.first()

    with patch.object(Missive, "can_billings", return_value=True), patch.object(
        Missive, "get_billings"
    ) as get_billings:
        _process_event(
            {
                "event": "delivered",
                "occurred_at": "2026-06-12T12:00:00Z",
                "recipient": {"id": str(target.id)},
                "raw": {"resource_name": "recipients"},
            },
            missive,
        )

    assert get_billings.call_count == 1


def test_nothing_is_billed_when_the_provider_has_no_billing_service():
    missive = _missive_with_recipients(4)

    with patch.object(Missive, "can_billings", return_value=False), patch.object(
        Missive, "get_billings"
    ) as get_billings:
        _process_event(_accepted_event(), missive)

    get_billings.assert_not_called()


def test_request_event_does_not_fetch_billings():
    missive = _missive_with_recipients(1)

    with patch.object(Missive, "can_billings", return_value=True), patch.object(
        Missive, "get_billings"
    ) as get_billings:
        MissiveEvent.objects.create(
            missive=missive,
            event=MissiveEventType.REQUEST,
            client_initiated=True,
        )

    get_billings.assert_not_called()


def test_fetch_missive_billings_swallows_provider_errors():
    missive = _missive_with_recipients(1)

    with patch.object(
        Missive, "get_billings", side_effect=RuntimeError("billing down")
    ):
        fetch_missive_billings(str(missive.pk))

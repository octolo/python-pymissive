"""An event row is targeted by pk only from the trusted call path.

``trace`` / ``raw`` is the provider request body copied verbatim (providerkit
sets ``normalized["raw"] = data``), and the webhook endpoint is unauthenticated,
so honouring a ``pk`` found there let anyone rewrite any event row — ids are a
sequential ``BigAutoField``, unlike the UUIDs used everywhere else. ``replay()``
still needs to target its own row, so it passes the pk as an argument instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from django.utils import timezone

from django_pymissive.events import _process_event
from django_pymissive.models import MissiveRecipientEmail, MissiveType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive(subject, external_id):
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL, subject=subject, external_id=external_id
    )
    recipient = MissiveRecipientEmail.objects.create(
        missive=missive, name=subject, email=f"{external_id}@example.com"
    )
    return missive, recipient


def test_pk_from_the_payload_does_not_rewrite_another_event():
    victim, victim_recipient = _missive("Invoice", "victim-1")
    proof = MissiveEvent.objects.create(
        missive=victim,
        recipient=victim_recipient,
        event="delivered",
        reason="Handed to the recipient",
        occurred_at=timezone.now(),
        trace={"provider": "maileva"},
    )

    attacker, attacker_recipient = _missive("Attacker", "attacker-1")
    forged = {
        "event": "failed",
        "occurred_at": "2026-09-13T10:00:00Z",
        "recipient": {"id": str(attacker_recipient.id)},
        "reason": "attacker controlled",
        "raw": {"pk": proof.pk, "payload": "attacker controlled"},
    }

    _process_event(forged, attacker)

    proof.refresh_from_db()
    assert proof.event == "delivered"
    assert proof.missive_id == victim.pk
    assert proof.recipient_id == victim_recipient.pk
    assert proof.reason == "Handed to the recipient"
    # The forged event is still ingested — on the attacker's own missive.
    assert MissiveEvent.objects.filter(missive=attacker, event="failed").count() == 1


def test_pk_from_the_payload_does_not_seize_an_unused_id():
    """Even with no row to overwrite, the payload must not choose the row id."""
    missive, recipient = _missive("Invoice", "m-1")
    forged = {
        "event": "delivered",
        "occurred_at": "2026-09-13T10:00:00Z",
        "recipient": {"id": str(recipient.id)},
        "raw": {"pk": 424242},
    }

    _process_event(forged, missive)

    created = MissiveEvent.objects.get(missive=missive)
    assert created.pk != 424242


def test_replay_updates_its_own_row_instead_of_duplicating():
    missive, recipient = _missive("Invoice", "m-1")
    stored = MissiveEvent.objects.create(
        missive=missive,
        recipient=recipient,
        event="processed",
        reason="In progress",
        occurred_at=timezone.now(),
        trace={"raw": {"status": "processed"}},
    )

    # The provider re-normalizes the stored payload into a newer event. The
    # business key therefore differs — only the pk can target the same row.
    provider = MagicMock()
    provider._provider.call_service_formatted.return_value = [{
        "event": "delivered",
        "occurred_at": "2026-09-13T10:00:00Z",
        "recipient": {"id": str(recipient.id)},
        "reason": "Handed to the recipient",
        "raw": {"status": "delivered"},
    }]

    with patch.object(Missive, "provider", new_callable=PropertyMock) as provider_prop:
        provider_prop.return_value = provider
        stored.replay()

    assert MissiveEvent.objects.count() == 1
    stored.refresh_from_db()
    assert stored.event == "delivered"
    assert stored.reason == "Handed to the recipient"
    assert stored.trace == {"status": "delivered"}


def test_replay_does_not_push_a_pk_into_the_provider_payload():
    """The pk travels as an argument, not inside the untrusted payload."""
    missive, recipient = _missive("Invoice", "m-1")
    stored = MissiveEvent.objects.create(
        missive=missive,
        recipient=recipient,
        event="processed",
        occurred_at=timezone.now(),
        trace={"raw": {"status": "processed"}},
    )

    provider = MagicMock()
    provider._provider.call_service_formatted.return_value = []

    with patch.object(Missive, "provider", new_callable=PropertyMock) as provider_prop:
        provider_prop.return_value = provider
        with pytest.raises(ValueError):
            stored.replay()

    payload = provider._provider.call_service_formatted.call_args.kwargs["payload"]
    assert payload == [{"status": "processed"}]

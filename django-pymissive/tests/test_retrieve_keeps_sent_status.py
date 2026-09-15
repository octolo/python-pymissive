"""Retrieve / « Statut » must not put a sent missive back to ``DRAFT``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models import MissiveRecipientEmail
from django_pymissive.models.choices import MissiveEventType, MissiveStatus, MissiveType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.PROCESSING,
        "external_id": "sent-1",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_set_status_does_not_regress_sent_missive_to_draft():
    """The send REQUEST used to be recipient-less → counts (0,0,0,0) → DRAFT."""
    missive = _missive()
    MissiveEvent.objects.create(
        missive=missive, event=MissiveEventType.REQUEST, client_initiated=True
    )
    missive.set_status()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING


def test_send_fans_request_out_to_recipients_so_retrieve_stays_processing(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _missive(status=MissiveStatus.DRAFT, external_id=None)
    recipients = [
        MissiveRecipientEmail.objects.create(missive=missive, email=f"r{i}@ex.com")
        for i in range(2)
    ]

    with (
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "get_serialized_data", return_value={}),
        patch.object(Missive, "set_locally_ifnull"),
        patch.object(
            Missive, "call_provider_service", return_value={"external_id": "prov-1"}
        ),
    ):
        missive.send_missive()

    assert (
        MissiveEvent.objects.filter(
            missive=missive, event=MissiveEventType.REQUEST, recipient__isnull=False
        ).count()
        == 2
    )
    assert not MissiveEvent.objects.filter(
        missive=missive, recipient__isnull=True
    ).exists()

    with patch.object(
        Missive, "call_provider_service", return_value={}
    ):
        missive.retrieve_missive()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING
    for recipient in recipients:
        recipient.refresh_from_db()
        assert recipient.status == MissiveStatus.PROCESSING

"""``CANCELLED`` is terminal: ``set_status()`` must not restore a sendable status."""

from __future__ import annotations

import pytest

from django_pymissive.models import MissiveRecipientEmail
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_set_status_keeps_cancelled_even_without_events():
    missive = _missive(status=MissiveStatus.CANCELLED)
    missive.set_status()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.CANCELLED


def test_set_status_does_not_leave_cancelled_for_later_delivery_events():
    missive = _missive(status=MissiveStatus.CANCELLED)
    recipient = MissiveRecipientEmail.objects.create(
        missive=missive, email="ok@example.com"
    )
    MissiveEvent.objects.create(
        missive=missive, recipient=recipient, event="delivered"
    )
    missive.set_status()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.CANCELLED


def test_set_status_derives_cancelled_from_cancelled_events():
    missive = _missive()
    recipient = MissiveRecipientEmail.objects.create(
        missive=missive, email="stop@example.com"
    )
    MissiveEvent.objects.create(
        missive=missive, recipient=recipient, event="cancelled"
    )
    missive.set_status()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.CANCELLED
    recipient.set_status()
    recipient.refresh_from_db()
    assert recipient.status == MissiveStatus.CANCELLED

"""The internal flag is a plain column on Missive."""

from __future__ import annotations

import pytest

from django_pymissive.models import Missive
from django_pymissive.models.choices import MissiveStatus, MissiveType

pytestmark = pytest.mark.django_db


def test_is_internal_defaults_to_false():
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Client",
        body_text="Hello",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )
    assert missive.is_internal is False


def test_is_internal_can_be_set():
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Note",
        body_text="Hello",
        sender_email="desk@example.com",
        status=MissiveStatus.DRAFT,
        is_internal=True,
    )
    assert Missive.objects.filter(pk=missive.pk, is_internal=True).exists()

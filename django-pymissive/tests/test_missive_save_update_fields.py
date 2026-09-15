"""Targeted ``Missive.save(update_fields=…)`` must not recompute defaults."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.config import MissiveConfig
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


def test_status_only_save_does_not_query_missive_config():
    missive = _missive()
    missive.status = MissiveStatus.PROCESSING
    with patch.object(MissiveConfig.objects, "filter") as filt:
        missive.save(update_fields=["status"])
    filt.assert_not_called()


def test_status_only_save_does_not_apply_or_discard_defaults():
    missive = _missive()
    MissiveConfig.objects.create(
        missive_type=MissiveType.EMAIL, default_provider="brevo"
    )
    assert not missive.provider

    missive.status = MissiveStatus.PROCESSING
    missive.save(update_fields=["status"])
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING
    assert not missive.provider

    missive.save()
    missive.refresh_from_db()
    assert missive.provider == "brevo"


def test_full_save_still_fills_support_and_sender():
    missive = Missive(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        status=MissiveStatus.DRAFT,
    )
    missive.save()
    missive.refresh_from_db()
    assert missive.missive_support
    assert missive.acknowledgement
    assert missive.delivery_mode
    assert missive.priority

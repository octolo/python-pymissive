"""Data remap of stored ``lre`` / ``postal`` values in migration 0023."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import AcknowledgementLevel, MissiveType
from django_pymissive.models.config import MissiveConfig
from django_pymissive.models.missive import Missive
from django_pymissive.models.scheduler import MissiveScheduledCampaign

_migration = import_module(
    "django_pymissive.migrations.0023_rename_acknowledgement_lre_missivecampaign_acknowledgement_letter_and_more"
)
remap_legacy_postal_types = _migration.remap_legacy_postal_types
target_type_for_legacy_postal = _migration.target_type_for_legacy_postal

pytestmark = pytest.mark.django_db


def _plant(missive: Missive, missive_type: str) -> None:
    Missive.objects.filter(pk=missive.pk).update(missive_type=missive_type)


class _LegacyMissiveManager:
    def filter(self, *args, **kwargs):
        if "campaign_id" in kwargs:
            kwargs["campaign_step__campaign_id"] = kwargs.pop("campaign_id")
        return Missive.objects.filter(*args, **kwargs)


class _LegacyMissive:
    objects = _LegacyMissiveManager()


class _LegacyApps:
    def get_model(self, app_label, model_name):
        if app_label == "django_pymissive" and model_name == "Missive":
            return _LegacyMissive
        return apps.get_model(app_label, model_name)


legacy_apps = _LegacyApps()


def _step(campaign, position, missive_type):
    return CampaignStep.objects.create(
        campaign=campaign,
        position=position,
        missive_type=missive_type,
    )


def test_target_type_for_legacy_postal():
    assert target_type_for_legacy_postal("postal", None) == "letter"
    assert target_type_for_legacy_postal("lre", None) == "letter"
    assert target_type_for_legacy_postal("lre", "") == "letter"
    assert target_type_for_legacy_postal("lre", "basic_delivery") == "letter"
    assert target_type_for_legacy_postal("lre", "acknowledgement_of_receipt") == "registered_letter"
    assert target_type_for_legacy_postal("email", None) is None


def test_remap_splits_lre_on_acknowledgement_and_rewrites_postal():
    campaign = MissiveCampaign.objects.create(subject="postal split")
    step = _step(campaign, 1, MissiveType.LETTER)
    leftover_postal = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="old postal",
    )
    simple = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="lre basic",
        acknowledgement=AcknowledgementLevel.BASIC_DELIVERY,
    )
    registered = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="lre ar",
        acknowledgement=AcknowledgementLevel.ACKNOWLEDGEMENT_OF_RECEIPT,
    )
    untouched = Missive.objects.create(missive_type=MissiveType.EMAIL, subject="email")
    _plant(leftover_postal, "postal")
    _plant(simple, "lre")
    _plant(registered, "lre")

    remap_legacy_postal_types(legacy_apps, None)

    leftover_postal.refresh_from_db()
    simple.refresh_from_db()
    registered.refresh_from_db()
    untouched.refresh_from_db()
    assert leftover_postal.missive_type == MissiveType.LETTER
    assert simple.missive_type == MissiveType.LETTER
    assert registered.missive_type == MissiveType.REGISTERED_LETTER
    assert untouched.missive_type == MissiveType.EMAIL


def test_remap_scheduled_uses_campaign_targets_and_clones_mixed_pending():
    campaign = MissiveCampaign.objects.create(subject="mixed pending")
    step = _step(campaign, 1, MissiveType.LETTER)
    simple = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="basic",
        acknowledgement=AcknowledgementLevel.BASIC_DELIVERY,
    )
    registered = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="ar",
        acknowledgement=AcknowledgementLevel.ACKNOWLEDGEMENT_OF_RECEIPT,
    )
    _plant(simple, "lre")
    _plant(registered, "lre")
    pending = MissiveScheduledCampaign.objects.create(campaign=campaign, missive_type="lre")
    already_sent = MissiveScheduledCampaign.objects.create(
        campaign=campaign,
        missive_type="lre",
        send_date=timezone.now(),
        ended_at=timezone.now(),
    )

    remap_legacy_postal_types(legacy_apps, None)

    pending.refresh_from_db()
    already_sent.refresh_from_db()
    assert pending.missive_type == MissiveType.REGISTERED_LETTER
    assert already_sent.missive_type == MissiveType.REGISTERED_LETTER
    clones = list(MissiveScheduledCampaign.objects.filter(campaign=campaign, missive_type=MissiveType.LETTER))
    assert len(clones) == 1
    assert clones[0].send_date is None


def test_remap_config_lre_becomes_registered_and_seeds_letter():
    MissiveConfig.objects.create(missive_type="lre", default_provider="maileva")

    remap_legacy_postal_types(apps, None)

    assert not MissiveConfig.objects.filter(missive_type="lre").exists()
    registered = MissiveConfig.objects.get(missive_type=MissiveType.REGISTERED_LETTER)
    letter = MissiveConfig.objects.get(missive_type=MissiveType.LETTER)
    assert registered.default_provider == "maileva"
    assert letter.default_provider == "maileva"


def test_remap_config_postal_becomes_letter_without_touching_existing_registered():
    MissiveConfig.objects.create(missive_type="postal", default_provider="maileva")
    MissiveConfig.objects.create(missive_type=MissiveType.REGISTERED_LETTER, default_provider="other")

    remap_legacy_postal_types(apps, None)

    assert not MissiveConfig.objects.filter(missive_type="postal").exists()
    assert MissiveConfig.objects.get(missive_type=MissiveType.LETTER).default_provider == "maileva"
    assert MissiveConfig.objects.get(missive_type=MissiveType.REGISTERED_LETTER).default_provider == "other"

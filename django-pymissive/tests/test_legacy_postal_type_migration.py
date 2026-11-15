"""Data remap of stored ``lre`` / ``postal`` values in migration 0023."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.config import MissiveConfig
from django_pymissive.models.missive import Missive

_migration = import_module(
    "django_pymissive.migrations.0023_rename_acknowledgement_lre_missivecampaign_acknowledgement_letter_and_more"
)
remap_legacy_postal_types = _migration.remap_legacy_postal_types
target_type_for_legacy_postal = _migration.target_type_for_legacy_postal

pytestmark = pytest.mark.django_db

_legacy_acknowledgements = {}


def _plant(missive: Missive, missive_type: str) -> None:
    Missive.objects.filter(pk=missive.pk).update(missive_type=missive_type)


class _LegacyMissiveManager:
    def filter(self, *args, **kwargs):
        if "campaign_id" in kwargs:
            kwargs["campaign_step__campaign_id"] = kwargs.pop("campaign_id")
        acknowledgement = kwargs.pop("acknowledgement", None)
        queryset = Missive.objects.filter(*args, **kwargs)
        if acknowledgement is not None:
            matching_ids = [
                missive_id for missive_id, value in _legacy_acknowledgements.items() if value == acknowledgement
            ]
            queryset = queryset.filter(pk__in=matching_ids)
        return queryset


class _LegacyMissive:
    objects = _LegacyMissiveManager()


class _LegacyScheduledQuery(list):
    def iterator(self):
        return iter(self)


class _LegacyScheduledRow:
    def __init__(self, **values):
        defaults = {
            "campaign_id": None,
            "scheduled_send_date": None,
            "missive_type": "*",
            "retry_failed": False,
            "task_content_type_id": None,
            "task_object_id": None,
            "task_object_arguments": {},
            "external_task_backend": "",
            "additional_config": {},
            "send_date": None,
            "ended_at": None,
        }
        for name, value in {**defaults, **values}.items():
            setattr(self, name, value)

    def refresh_from_db(self):
        return None

    def save(self, update_fields=None):
        return None


class _LegacyScheduledManager:
    def __init__(self):
        self.rows = []

    def create(self, **values):
        row = _LegacyScheduledRow(**values)
        self.rows.append(row)
        return row

    def filter(self, **kwargs):
        rows = self.rows
        for lookup, value in kwargs.items():
            if lookup.endswith("__in"):
                field = lookup.removesuffix("__in")
                rows = [row for row in rows if getattr(row, field) in value]
            else:
                rows = [row for row in rows if getattr(row, lookup) == value]
        return _LegacyScheduledQuery(rows)


class _LegacyScheduled:
    objects = _LegacyScheduledManager()


class _LegacyApps:
    def get_model(self, app_label, model_name):
        if app_label == "django_pymissive" and model_name == "Missive":
            return _LegacyMissive
        if app_label == "django_pymissive" and model_name == "MissiveScheduledCampaign":
            return _LegacyScheduled
        return apps.get_model(app_label, model_name)


legacy_apps = _LegacyApps()


@pytest.fixture(autouse=True)
def clear_legacy_state():
    _legacy_acknowledgements.clear()
    _LegacyScheduled.objects.rows.clear()


def _step(campaign, position, missive_type):
    return CampaignStep.objects.create(
        campaign=campaign,
        position=position,
        missive_type=missive_type,
    )


def _set_acknowledgement(missive, value):
    _legacy_acknowledgements[missive.pk] = value


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
    )
    registered = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="lre ar",
    )
    _set_acknowledgement(simple, "basic_delivery")
    _set_acknowledgement(registered, "acknowledgement_of_receipt")
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
    )
    registered = Missive.objects.create(
        campaign_step=step,
        missive_type=MissiveType.LETTER,
        subject="ar",
    )
    _set_acknowledgement(simple, "basic_delivery")
    _set_acknowledgement(registered, "acknowledgement_of_receipt")
    _plant(simple, "lre")
    _plant(registered, "lre")
    pending = _LegacyScheduled.objects.create(campaign_id=campaign.pk, missive_type="lre")
    already_sent = _LegacyScheduled.objects.create(
        campaign_id=campaign.pk,
        missive_type="lre",
        send_date=timezone.now(),
        ended_at=timezone.now(),
    )

    remap_legacy_postal_types(legacy_apps, None)

    pending.refresh_from_db()
    already_sent.refresh_from_db()
    assert pending.missive_type == MissiveType.REGISTERED_LETTER
    assert already_sent.missive_type == MissiveType.REGISTERED_LETTER
    clones = [
        row
        for row in _LegacyScheduled.objects.rows
        if row.campaign_id == campaign.pk and row.missive_type == MissiveType.LETTER
    ]
    assert len(clones) == 1
    assert clones[0].send_date is None


def test_remap_config_lre_becomes_registered_and_seeds_letter():
    MissiveConfig.objects.create(missive_type="lre", default_provider="maileva")

    remap_legacy_postal_types(legacy_apps, None)

    assert not MissiveConfig.objects.filter(missive_type="lre").exists()
    registered = MissiveConfig.objects.get(missive_type=MissiveType.REGISTERED_LETTER)
    letter = MissiveConfig.objects.get(missive_type=MissiveType.LETTER)
    assert registered.default_provider == "maileva"
    assert letter.default_provider == "maileva"


def test_remap_config_postal_becomes_letter_without_touching_existing_registered():
    MissiveConfig.objects.create(missive_type="postal", default_provider="maileva")
    MissiveConfig.objects.create(missive_type=MissiveType.REGISTERED_LETTER, default_provider="other")

    remap_legacy_postal_types(legacy_apps, None)

    assert not MissiveConfig.objects.filter(missive_type="postal").exists()
    assert MissiveConfig.objects.get(missive_type=MissiveType.LETTER).default_provider == "maileva"
    assert MissiveConfig.objects.get(missive_type=MissiveType.REGISTERED_LETTER).default_provider == "other"

"""Default sender from ``PYMISSIVE_DEFAULT_SENDER``.

Campaigns fill every empty sender slot. Missives fill only the fields of
their type, and only when the campaign does not already provide them.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db

_DEFAULTS = {
    "name": "Octolo",
    "email": "contact@octolo.tech",
    "phone": "+33123456789",
    "address": {
        "organization": "Octolo",
        "address_line1": "1 rue de la Paix",
        "postal_code": "75002",
        "city": "Paris",
        "country": "France",
    },
}


def _campaign(**kw) -> MissiveCampaign:
    return MissiveCampaign.objects.create(subject="Camp", **kw)


def _missive(missive_type, **kw) -> Missive:
    return Missive.objects.create(
        missive_type=missive_type,
        status=MissiveStatus.DRAFT,
        **kw,
    )


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_campaign_fills_every_empty_sender():
    campaign = _campaign()
    assert campaign.sender_email_name == "Octolo"
    assert campaign.sender_phone_name == "Octolo"
    assert campaign.sender_address_name == "Octolo"
    assert campaign.sender_email == "contact@octolo.tech"
    assert str(campaign.sender_phone) == "+33123456789"
    assert campaign.sender_address["organization"] == "Octolo"
    assert campaign.sender_address["city"] == "Paris"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_campaign_keeps_explicit_sender():
    campaign = _campaign(
        sender_email_name="Custom",
        sender_email="other@example.com",
        sender_phone_name="SMS Brand",
        sender_phone="+33612345678",
    )
    assert campaign.sender_email_name == "Custom"
    assert campaign.sender_email == "other@example.com"
    assert campaign.sender_phone_name == "SMS Brand"
    assert str(campaign.sender_phone) == "+33612345678"
    assert campaign.sender_address_name == "Octolo"
    assert campaign.sender_address["organization"] == "Octolo"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_email_missive_fills_name_and_email():
    missive = _missive(MissiveType.EMAIL)
    assert missive.sender_name == "Octolo"
    assert missive.sender_email == "contact@octolo.tech"
    assert not missive.sender_phone
    assert not missive.sender_address


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_sms_missive_fills_name_and_phone():
    missive = _missive(MissiveType.SMS)
    assert missive.sender_name == "Octolo"
    assert str(missive.sender_phone) == "+33123456789"
    assert not missive.sender_email
    assert not missive.sender_address


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_registered_letter_missive_fills_name_and_address():
    missive = _missive(MissiveType.REGISTERED_LETTER)
    assert missive.sender_name == "Octolo"
    assert missive.sender_address["organization"] == "Octolo"
    assert not missive.sender_email
    assert not missive.sender_phone


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_missive_keeps_explicit_sender():
    missive = _missive(
        MissiveType.EMAIL,
        sender_name="Local",
        sender_email="local@example.com",
    )
    assert missive.sender_name == "Local"
    assert missive.sender_email == "local@example.com"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_missive_skips_settings_when_campaign_has_sender():
    campaign = _campaign(
        sender_email_name="Campaign Sender",
        sender_email="campaign@example.com",
    )
    missive = _missive(MissiveType.EMAIL, campaign=campaign)
    assert missive.sender_name is None
    assert missive.sender_email is None
    assert missive.get_locally_or_campaign_value("sender_name") == "Campaign Sender"
    assert missive.get_locally_or_campaign_value("sender_email") == "campaign@example.com"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_missive_fills_when_campaign_sender_empty_for_that_support():
    campaign = MissiveCampaign(
        subject="Camp",
        sender_email_name="",
        sender_email=None,
        sender_phone_name="",
        sender_phone=None,
        sender_address_name="",
        sender_address=None,
    )
    MissiveCampaign.objects.bulk_create([campaign])
    campaign = MissiveCampaign.objects.get(pk=campaign.pk)
    missive = _missive(MissiveType.EMAIL, campaign=campaign)
    assert missive.sender_name == "Octolo"
    assert missive.sender_email == "contact@octolo.tech"


@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_empty_setting_leaves_sender_blank():
    campaign = _campaign()
    missive = _missive(MissiveType.EMAIL)
    assert not campaign.sender_email
    assert not campaign.sender_email_name
    assert not missive.sender_name
    assert not missive.sender_email


@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_full_clean_requires_sender_when_no_defaults():
    missive = _missive(MissiveType.EMAIL, subject="Hello", body_text="Body")
    with pytest.raises(ValidationError) as exc:
        missive.full_clean()
    assert "sender_email" in exc.value.message_dict


@override_settings(PYMISSIVE_DEFAULT_SENDER={"name": "Octolo"})
def test_full_clean_requires_sender_when_default_missing_for_type():
    missive = _missive(MissiveType.EMAIL, subject="Hello", body_text="Body")
    with pytest.raises(ValidationError) as exc:
        missive.full_clean()
    assert "sender_email" in exc.value.message_dict
    assert missive.sender_name == "Octolo"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_full_clean_fills_empty_sender_on_existing_missive():
    missive = _missive(MissiveType.EMAIL, subject="Hello", body_text="Body")
    Missive.objects.filter(pk=missive.pk).update(sender_name=None, sender_email=None)
    missive.refresh_from_db()
    assert missive.sender_email is None

    missive.full_clean()
    assert missive.sender_name == "Octolo"
    assert missive.sender_email == "contact@octolo.tech"

    missive.save()
    missive.refresh_from_db()
    assert missive.sender_email == "contact@octolo.tech"


@override_settings(PYMISSIVE_DEFAULT_SENDER=_DEFAULTS)
def test_retrieved_missive_does_not_refill_sender():
    missive = _missive(
        MissiveType.EMAIL,
        sender_name="Local",
        sender_email="local@example.com",
        external_id="ext-1",
    )
    missive.sender_name = None
    missive.sender_email = None
    missive.save()
    missive.refresh_from_db()
    assert missive.sender_name is None
    assert missive.sender_email is None

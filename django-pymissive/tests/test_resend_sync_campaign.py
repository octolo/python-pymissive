"""Tests for ``sync_campaign`` on duplicate/resend and the no-campaign clear guard.

Covers:
- ``duplicate_missive(sync_campaign=True)`` overwrites campaign-sourced fields
  with the campaign's current values (incl. the ``sender_name`` →
  ``sender_email_name`` mapping and ``additional_context``).
- A campaign-empty field keeps the duplicated missive's local value.
- The default resend path (``sync_campaign=False``) clears campaign-sourced
  fields so they are lazily re-filled at send time.
- ``clear_campaign_sourced_fields`` is a no-op without a campaign, so resending
  a campaign-less missive preserves its own content.

These exercise the duplication layer directly (no provider call / no send).
"""

from __future__ import annotations

import pytest

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _campaign(**kw) -> MissiveCampaign:
    return MissiveCampaign.objects.create(**kw)


def _email_missive(campaign=None, **kw) -> Missive:
    return Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.EMAIL,
        status=MissiveStatus.DRAFT,
        **kw,
    )


def test_sync_campaign_overwrites_local_overrides():
    campaign = _campaign(
        subject="Campaign subject",
        email_body_text="Campaign body",
        sender_email_name="Campaign Sender",
        sender_email="campaign@example.com",
    )
    missive = _email_missive(
        campaign,
        subject="Local subject",
        body_text="Local body",
        sender_name="Local Sender",
        sender_email="local@example.com",
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.subject == "Campaign subject"
    assert new.body_text == "Campaign body"
    # sender_name maps to the campaign's sender_email_name for email support
    assert new.sender_name == "Campaign Sender"
    assert new.sender_email == "campaign@example.com"


def test_sync_campaign_keeps_value_when_campaign_field_empty():
    # Campaign has a subject but no body_text → body_text override is preserved.
    campaign = _campaign(subject="Campaign subject")
    missive = _email_missive(
        campaign,
        subject="Local subject",
        body_text="Local body",
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.subject == "Campaign subject"
    assert new.body_text == "Local body"


def test_sync_campaign_copies_additional_context():
    campaign = _campaign(
        subject="Campaign subject",
        additional_context={"template_id": 1, "params": {"code": "42"}},
    )
    missive = _email_missive(campaign, subject="Local subject")

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.additional_context == {"template_id": 1, "params": {"code": "42"}}


def test_default_resend_clears_campaign_sourced_fields():
    campaign = _campaign(subject="Campaign subject")
    missive = _email_missive(
        campaign,
        subject="Local subject",
        body_text="Local body",
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=False)
    new.refresh_from_db()

    # Cleared so they are lazily re-filled from the campaign at send time.
    assert new.subject is None
    assert new.body_text is None


def _letter_missive(campaign=None, **kw) -> Missive:
    return Missive.objects.create(
        campaign=campaign,
        missive_type=MissiveType.LETTER,
        status=MissiveStatus.DRAFT,
        **kw,
    )


def test_letter_printing_defaults_to_duplex_true_color_false():
    missive = _letter_missive()

    assert missive.duplex_printing is True
    assert missive.color_printing is False
    assert missive.get_duplex_printing() is True
    assert missive.get_color_printing() is False
    data = missive.get_serialized_data(attachments=False)
    assert data["duplex_printing"] is True
    assert data["color_printing"] is False


def test_letter_printing_local_false_is_kept():
    campaign = _campaign(
        subject="Postal campaign",
        duplex_printing_letter=True,
        color_printing_letter=True,
    )
    missive = _letter_missive(
        campaign,
        duplex_printing=False,
        color_printing=False,
    )

    assert missive.get_duplex_printing() is False
    assert missive.get_color_printing() is False
    missive.set_locally_ifnull()
    missive.refresh_from_db()
    assert missive.duplex_printing is False
    assert missive.color_printing is False


def test_sync_campaign_applies_letter_printing_false():
    campaign = _campaign(
        subject="Postal campaign",
        duplex_printing_letter=False,
        color_printing_letter=False,
    )
    missive = _letter_missive(
        campaign,
        duplex_printing=True,
        color_printing=True,
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.duplex_printing is False
    assert new.color_printing is False


def test_clear_is_noop_without_campaign():
    missive = _email_missive(
        subject="Keep me",
        body_text="Keep body",
        sender_name="Keep Sender",
    )

    new = missive.duplicate_missive(resend=True)
    new.refresh_from_db()

    # No campaign → nothing would refill, so content must be preserved.
    assert new.subject == "Keep me"
    assert new.body_text == "Keep body"
    assert new.sender_name == "Keep Sender"

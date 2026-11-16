"""Tests for ``sync_campaign`` on duplicate/resend and the no-campaign clear guard.

Covers:
- ``duplicate_missive(sync_campaign=True)`` overwrites step-sourced fields
  with the step's current values and copies campaign context.
- An empty step field keeps the duplicated missive's local value.
- The default resend path (``sync_campaign=False``) clears campaign-sourced
  fields so they are lazily re-filled at send time.
- ``clear_campaign_sourced_fields`` is a no-op without a campaign, so resending
  a campaign-less missive preserves its own content.

These exercise the duplication layer directly (no provider call / no send).
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _campaign(**kw) -> MissiveCampaign:
    return MissiveCampaign.objects.create(**kw)


def _step(campaign, missive_type, **kwargs) -> CampaignStep:
    return CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=missive_type,
        **kwargs,
    )


def _email_missive(campaign=None, **kw) -> Missive:
    if campaign is not None and "campaign_step" not in kw:
        kw["campaign_step"] = _step(campaign, MissiveType.EMAIL)
    return Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        status=MissiveStatus.DRAFT,
        **kw,
    )


def test_sync_campaign_overwrites_local_overrides():
    campaign = _campaign(
        subject="Campaign subject",
    )
    step = _step(
        campaign,
        MissiveType.EMAIL,
        subject="Campaign subject",
        body_text="Campaign body",
        sender_name="Campaign Sender",
        sender_email="campaign@example.com",
    )
    missive = _email_missive(
        campaign,
        campaign_step=step,
        subject="Local subject",
        body_text="Local body",
        sender_name="Local Sender",
        sender_email="local@example.com",
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.subject == "Campaign subject"
    assert new.body_text == "Campaign body"
    assert new.sender_name == "Campaign Sender"
    assert new.sender_email == "campaign@example.com"


def test_sync_campaign_keeps_value_when_campaign_field_empty():
    # Campaign has a subject but no body_text → body_text override is preserved.
    campaign = _campaign(subject="Campaign subject")
    step = _step(campaign, MissiveType.EMAIL, subject="Campaign subject")
    missive = _email_missive(
        campaign,
        campaign_step=step,
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
    step = _step(campaign, MissiveType.EMAIL, subject="Campaign subject", body_text="Campaign body")
    missive = _email_missive(
        campaign,
        campaign_step=step,
        subject="Local subject",
        body_text="Local body",
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=False)
    new.refresh_from_db()

    # Cleared so they are lazily re-filled from the campaign at send time.
    assert new.subject is None
    assert new.body_text is None


def _letter_missive(campaign=None, **kw) -> Missive:
    if campaign is not None and "campaign_step" not in kw:
        kw["campaign_step"] = _step(campaign, MissiveType.LETTER)
    return Missive.objects.create(
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
    campaign = _campaign(subject="Postal campaign")
    step = _step(campaign, MissiveType.LETTER, duplex_printing=True, color_printing=False)
    missive = _letter_missive(
        campaign,
        campaign_step=step,
        duplex_printing=False,
        color_printing=False,
    )

    assert missive.get_duplex_printing() is False
    assert missive.get_color_printing() is False
    missive.set_locally_ifnull()
    missive.refresh_from_db()
    assert missive.duplex_printing is False
    assert missive.color_printing is False


def test_registered_letter_printing_uses_registered_campaign_fields():
    campaign = _campaign(subject="Postal campaign")
    registered_step = _step(
        campaign,
        MissiveType.REGISTERED_LETTER,
        duplex_printing=False,
        color_printing=True,
    )
    missive = Missive.objects.create(
        campaign_step=registered_step,
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
        duplex_printing=True,
        color_printing=False,
    )

    new = missive.duplicate_missive(resend=True, sync_campaign=True)
    new.refresh_from_db()

    assert new.duplex_printing is False
    assert new.color_printing is True
    letter_step = CampaignStep.objects.create(
        campaign=campaign,
        position=2,
        missive_type=MissiveType.LETTER,
        duplex_printing=True,
        color_printing=False,
    )
    letter = _letter_missive(
        campaign,
        campaign_step=letter_step,
        duplex_printing=True,
        color_printing=True,
    )
    letter_new = letter.duplicate_missive(resend=True, sync_campaign=True)
    letter_new.refresh_from_db()
    assert letter_new.duplex_printing is True
    assert letter_new.color_printing is False


def test_campaign_named_id_is_generated_from_subject():
    campaign = _campaign(subject="Summer Campaign")
    campaign.refresh_from_db()
    assert campaign.named_id == "summer-campaign"


def test_campaign_named_id_uses_settings_generator():
    with override_settings(PYMISSIVE_CAMPAIGN_NAMED_ID_GENERATOR="tests.generators.test_campaign_named_id"):
        first = _campaign(subject="Summer Campaign")
        second = _campaign(subject="Summer Campaign")
    assert first.named_id == "test-summer-campaign"
    assert second.named_id == "test-summer-campaign-1"


def test_sync_campaign_applies_letter_printing_false():
    campaign = _campaign(subject="Postal campaign")
    step = _step(campaign, MissiveType.LETTER, duplex_printing=False, color_printing=False)
    missive = _letter_missive(
        campaign,
        campaign_step=step,
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


@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_resend_paths_follow_every_email_sourced_field():
    fields = Missive.get_campaign_sourced_fields("email")
    step_values = {
        "subject": "Step subject",
        "body_rich": "<p>step</p>",
        "body_rich_snapshot_html": "<p>step snapshot</p>",
        "body_text": "step text",
        "sender_name": "Step Sender",
        "sender_email": "step@example.com",
        "reply_to_name": "Step Reply",
        "reply_to_email": "reply-step@example.com",
    }
    local_values = {
        "subject": "Local subject",
        "body_rich": "<p>local</p>",
        "body_rich_snapshot_html": "<p>local snapshot</p>",
        "body_text": "local text",
        "sender_name": "Local Sender",
        "sender_email": "local@example.com",
        "reply_to_name": "Local Reply",
        "reply_to_email": "reply-local@example.com",
    }
    assert set(step_values) == set(fields)
    campaign = _campaign(subject="Campaign")
    step = _step(campaign, MissiveType.EMAIL, **step_values)
    missive = _email_missive(campaign, campaign_step=step, **local_values)

    synced = missive.duplicate_missive(resend=True, sync_campaign=True)
    synced.refresh_from_db()
    for name in fields:
        assert getattr(synced, name) == getattr(step, name)

    cleared = missive.duplicate_missive(resend=True, sync_campaign=False)
    cleared.refresh_from_db()
    for name in fields:
        assert getattr(cleared, name) in (None, "")

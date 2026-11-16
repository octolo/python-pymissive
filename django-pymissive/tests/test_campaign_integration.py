"""Integration services added for campaign statistics and recipient replacement."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django_pymissive.models import CampaignStep, CampaignTarget, Missive, MissiveCampaign, MissiveStatus, MissiveType
from django_pymissive.models.choices import MissiveRecipientType
from django_pymissive.services import build_campaign_send_recap, select, set_target_recipients

from tests.fakeapp.models import Contact

pytestmark = pytest.mark.django_db


def _campaign():
    return MissiveCampaign.objects.create(subject="Assemblée")


def _contact(email):
    return Contact.objects.create(first_name="Ada", last_name="Lovelace", email=email)


def test_set_recipients_replaces_one_role_and_keeps_the_others():
    campaign = _campaign()
    campaign.ensure_steps([("email", "Email", 1)])
    contact = _contact("ada-role@example.com")
    select(campaign, "email", contact)
    row = CampaignTarget.objects.get(campaign=campaign)
    row.add_recipient({"name": "Copy", "email": "copy@example.com"}, recipient_type=MissiveRecipientType.CC)

    stored = row.set_recipients(
        ["ada@example.com", {"name": "Ada", "email": "ada@example.com"}, "work@example.com"],
    )

    assert stored == ["ada@example.com", "work@example.com"]
    assert row.to_campaignrecipienttarget.get(recipient_type=MissiveRecipientType.RECIPIENT).values == stored
    assert row.to_campaignrecipienttarget.get(recipient_type=MissiveRecipientType.CC).values == [
        {"name": "Copy", "email": "copy@example.com"},
    ]

    row.set_recipients(["only@example.com"], clear_other_roles=True)
    assert list(row.to_campaignrecipienttarget.values_list("recipient_type", flat=True)) == [
        MissiveRecipientType.RECIPIENT,
    ]

    row.clear_recipients()
    assert not row.to_campaignrecipienttarget.filter(recipient_type=MissiveRecipientType.RECIPIENT).exists()


def test_set_target_recipients_updates_live_rows_in_one_batch():
    campaign = _campaign()
    campaign.ensure_steps([("email", "Email", 1), ("sms", "SMS", 2)])
    contacts = [_contact(f"ada{index}@example.com") for index in range(3)]
    select(campaign, "email", contacts)
    rows = list(CampaignTarget.objects.filter(campaign=campaign))
    rows[0].add_recipient({"name": "Copy", "email": "copy@example.com"}, recipient_type=MissiveRecipientType.CC)

    with CaptureQueriesContext(connection) as captured:
        updated = set_target_recipients(
            campaign,
            "email",
            {
                rows[0]: ["first@example.com", "first@example.com"],
                contacts[1]: ["second@example.com"],
                (Contact, rows[2].object_id): ["third@example.com"],
            },
            clear_other_roles=True,
        )

    assert updated == 3
    assert len(captured.captured_queries) < 12
    assert rows[0].to_campaignrecipienttarget.get(recipient_type=MissiveRecipientType.RECIPIENT).values == [
        "first@example.com",
    ]
    assert not rows[0].to_campaignrecipienttarget.exclude(recipient_type=MissiveRecipientType.RECIPIENT).exists()
    assert rows[1].to_campaignrecipienttarget.get().values == ["second@example.com"]
    assert rows[2].to_campaignrecipienttarget.get().values == ["third@example.com"]

    with CaptureQueriesContext(connection) as empty:
        assert set_target_recipients(campaign, "email", {}) == 0
    assert empty.captured_queries == []

    foreign = _campaign()
    foreign.ensure_steps([("email", "Email", 1)])
    with pytest.raises(ValueError, match="does not belong"):
        set_target_recipients(foreign, "email", {rows[0]: ["nope@example.com"]})

    with pytest.raises(TypeError, match="must be CampaignTarget"):
        set_target_recipients(campaign, "email", {rows[0].object_id: ["ambiguous@example.com"]})


def test_set_target_recipients_keeps_equal_object_ids_separate_between_models():
    campaign = _campaign()
    campaign.ensure_steps([("email", "Email", 1)])
    contact = _contact("same-id@example.com")
    other_model = _campaign()
    select(campaign, "email", [contact, other_model])

    assert contact.pk != other_model.pk
    CampaignTarget.objects.filter(
        campaign=campaign,
        content_type__model="missivecampaign",
    ).update(object_id=str(contact.pk))

    set_target_recipients(
        campaign,
        "email",
        {
            contact: ["contact@example.com"],
            (MissiveCampaign, contact.pk): ["campaign@example.com"],
        },
    )

    contact_row = CampaignTarget.objects.get(campaign=campaign, content_type__model="contact")
    campaign_row = CampaignTarget.objects.get(campaign=campaign, content_type__model="missivecampaign")
    assert contact_row.to_campaignrecipienttarget.get().values == ["contact@example.com"]
    assert campaign_row.to_campaignrecipienttarget.get().values == ["campaign@example.com"]


def test_recipient_replacement_refuses_a_materialized_target():
    campaign = _campaign()
    campaign.ensure_steps([("email", "Email", 1)])
    contact = _contact("materialized@example.com")
    select(campaign, "email", contact)
    row = CampaignTarget.objects.get(campaign=campaign)
    draft = Missive.objects.create(
        campaign_step=row.campaign_step,
        missive_type=MissiveType.EMAIL,
        subject="Draft",
        status=MissiveStatus.DRAFT,
    )
    row.attach_missive(draft)

    with pytest.raises(ValueError, match="live selection row"):
        row.set_recipients(["too-late@example.com"])
    with pytest.raises(ValueError, match="live selection row"):
        set_target_recipients(campaign, "email", {row: ["too-late@example.com"]})


def test_ensure_steps_is_idempotent_and_resolves_position_collisions(monkeypatch):
    campaign = _campaign()
    CampaignStep.objects.create(campaign=campaign, position=1, missive_type=MissiveType.EMAIL, label="Kept")
    saves_inside_atomic = []
    original_save = CampaignStep.save

    def tracked_save(step, *args, **kwargs):
        saves_inside_atomic.append(connection.in_atomic_block)
        return original_save(step, *args, **kwargs)

    monkeypatch.setattr(CampaignStep, "save", tracked_save)

    first = campaign.ensure_steps(
        [
            ("email", "Ignored", 1),
            ("sms", "SMS", 1),
            {"missive_type": "registered-letter", "label": "Courrier", "position": 4},
        ]
    )
    second = campaign.ensure_steps([("sms", "Again", 9), ("letter", "Courrier simple", 4)])

    assert first["email"].label == "Kept"
    assert first["sms"].position == 2
    assert first["registered_letter"].position == 4
    assert second["letter"].position == 5
    assert campaign.to_campaignstep.count() == 4
    assert campaign.get_step("registered-letter").label == "Courrier"
    assert saves_inside_atomic and all(saves_inside_atomic)
    with pytest.raises(ValueError, match="Unknown missive type"):
        campaign.ensure_steps([("postal", "No", 8)])


def test_get_step_reports_a_duplicate_and_can_return_the_first():
    campaign = _campaign()
    first = CampaignStep.objects.create(campaign=campaign, position=1, missive_type=MissiveType.EMAIL, label="First")
    CampaignStep.objects.create(campaign=campaign, position=2, missive_type=MissiveType.EMAIL, label="Second")

    with pytest.raises(ValueError, match="2 'email' steps"):
        campaign.get_step("email")
    assert campaign.get_step("email", require_unique=False) == first
    with pytest.raises(ValueError, match="no 'sms' step"):
        campaign.get_step("sms")


def test_send_recap_counts_targets_and_drafts_once():
    campaign = _campaign()
    campaign.ensure_steps(
        [
            ("email", "Email", 1),
            ("sms", "SMS", 2),
            ("letter", "Letter", 3),
        ]
    )
    email_contact = _contact("recap-email@example.com")
    letter_contact = _contact("recap-letter@example.com")
    select(campaign, "email", email_contact)
    select(campaign, "letter", letter_contact)
    letter_row = CampaignTarget.objects.get(campaign_step__missive_type=MissiveType.LETTER)
    letter_step = letter_row.campaign_step
    draft = Missive.objects.create(
        campaign_step=letter_step,
        missive_type=MissiveType.LETTER,
        subject="Draft",
        status=MissiveStatus.DRAFT,
    )
    letter_row.attach_missive(draft)
    sms_step = campaign.get_step("sms")
    Missive.objects.create(
        campaign_step=sms_step,
        missive_type=MissiveType.SMS,
        subject="Draft sms",
        status=MissiveStatus.DRAFT,
    )
    Missive.objects.create(
        campaign_step=campaign.get_step("email"),
        missive_type=MissiveType.EMAIL,
        subject="Sent",
        status=MissiveStatus.SUCCESS,
    )

    recap = build_campaign_send_recap(campaign)

    assert recap["targets"] == {"total": 1, "by_type": {MissiveType.EMAIL: 1}}
    assert recap["drafts"]["total"] == 2
    assert recap["drafts"]["by_type"][MissiveType.LETTER] == 1
    assert recap["drafts"]["by_type"][MissiveType.SMS] == 1
    assert recap["by_type"][MissiveType.EMAIL] == 1
    assert recap["total"] == 3
    assert recap["by_support"]["email"] == 1
    assert recap["by_support"]["phone"] == 1
    assert recap["by_support"]["address"] == 1
    assert MissiveType.LETTER not in recap["targets"]["by_type"]

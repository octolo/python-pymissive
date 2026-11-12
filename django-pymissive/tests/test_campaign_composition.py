"""Campaigns composed of ordered, typed steps."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_pymissive.models.attachment import MissiveBaseAttachment
from django_pymissive.models.campaign import MissiveCampaign, campaign_from_snapshot
from django_pymissive.models.campaign_step import (
    BrandedCampaignStep,
    CampaignStep,
    PostalCampaignStep,
)
from django_pymissive.models.campaign_target import CampaignTarget
from django_pymissive.models.choices import MissiveDeliveryMode, MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.scheduler import MissiveScheduledCampaign
from django_pymissive.services.drafts import materialize_missive
from django_pymissive.services.send import run_selection
from django_pymissive.services.targets import select
from tests.fakeapp.campaign_targets import build_campaign_contact
from tests.fakeapp.generators import create_campaign_contact

pytestmark = pytest.mark.django_db


def _campaign(subject="Launch", **kwargs) -> MissiveCampaign:
    return MissiveCampaign.objects.create(subject=subject, **kwargs)


def _step(campaign, position, missive_type, label="", **kwargs) -> CampaignStep:
    return CampaignStep.objects.create(
        campaign=campaign,
        position=position,
        label=label,
        missive_type=missive_type,
        **kwargs,
    )


def _file(campaign, name: str) -> MissiveBaseAttachment:
    return MissiveBaseAttachment.objects.create(
        campaign=campaign,
        attachment_file=ContentFile(name.encode(), name=name),
        priority=1,
        linked=False,
    )


def _missive(campaign, step, missive_type) -> Missive:
    return Missive.objects.create(
        campaign_step=step,
        missive_type=missive_type,
        subject="",
        status=MissiveStatus.DRAFT,
    )


def test_missive_campaign_is_derived_from_step_only():
    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.EMAIL)
    missive = _missive(campaign, step, MissiveType.EMAIL)
    standalone = Missive.objects.create(missive_type=MissiveType.EMAIL)

    assert missive.campaign == campaign
    assert missive.campaign_id == campaign.pk
    assert standalone.campaign is None
    assert standalone.campaign_id is None
    assert "campaign" not in {field.name for field in Missive._meta.get_fields()}


def test_campaign_step_count_annotations_include_total_sum():
    campaign = _campaign()
    _step(campaign, 1, MissiveType.EMAIL)
    _step(campaign, 2, MissiveType.EMAIL)
    _step(campaign, 3, MissiveType.SMS)

    annotated = MissiveCampaign.objects.with_counts(
        "count_step_email",
        "count_step_sms",
        "count_step",
    ).get(pk=campaign.pk)

    assert annotated.count_step_email == 2
    assert annotated.count_step_sms == 1
    assert annotated.count_step == 3


def test_two_email_steps_keep_their_own_content():
    campaign = _campaign(additional_context={"wave": "campaign"})
    invite = _step(
        campaign,
        1,
        MissiveType.EMAIL,
        "Invite",
        subject="You are invited",
        body_text="INVITE-BODY",
        additional_context={"wave": "invite"},
        body_processors=["invite.processor"],
    )
    reminder = _step(
        campaign,
        2,
        MissiveType.EMAIL,
        "Reminder",
        subject="A reminder",
        body_text="REMINDER-BODY",
        body_processors=["reminder.processor"],
    )
    campaign.body_processors = ["campaign.processor"]
    campaign.save(update_fields=["body_processors"])

    first = _missive(campaign, invite, MissiveType.EMAIL)
    second = _missive(campaign, reminder, MissiveType.EMAIL)

    assert first.get_locally_or_campaign_value("subject") == "You are invited"
    assert first.get_locally_or_campaign_value("body_text") == "INVITE-BODY"
    assert second.get_locally_or_campaign_value("subject") == "A reminder"
    assert second.get_locally_or_campaign_value("body_text") == "REMINDER-BODY"
    assert first.get_locally_or_campaign_value("subject") != campaign.subject
    first.set_locally_ifnull()
    assert first.additional_context == {"wave": "invite"}
    assert first.get_body_processors() == ["invite.processor"]
    assert second.get_body_processors() == ["reminder.processor"]


def test_two_postal_steps_keep_their_own_options():
    campaign = _campaign()
    letter = _step(
        campaign,
        1,
        MissiveType.LETTER,
        "Letter",
        body_rich="<p>LETTER-A</p>",
        duplex_printing=False,
        color_printing=True,
        delivery_mode=MissiveDeliveryMode.EXPRESS,
    )
    registered = _step(
        campaign,
        2,
        MissiveType.REGISTERED_LETTER,
        "Registered",
        body_rich="<p>LETTER-B</p>",
        duplex_printing=True,
        color_printing=False,
        delivery_mode=MissiveDeliveryMode.ECONOMIC,
    )

    first = _missive(campaign, letter, MissiveType.LETTER)
    second = _missive(campaign, registered, MissiveType.REGISTERED_LETTER)

    assert first.get_locally_or_campaign_value("body_rich") == "<p>LETTER-A</p>"
    assert first.get_locally_or_campaign_value("duplex_printing") is False
    assert first.get_locally_or_campaign_value("color_printing") is True
    assert first.get_delivery_mode() == MissiveDeliveryMode.EXPRESS
    assert second.get_locally_or_campaign_value("body_rich") == "<p>LETTER-B</p>"
    assert second.get_locally_or_campaign_value("duplex_printing") is True
    assert second.get_locally_or_campaign_value("color_printing") is False
    assert second.get_delivery_mode() == MissiveDeliveryMode.ECONOMIC

    postal_proxy = PostalCampaignStep.objects.get(pk=letter.pk)
    assert postal_proxy.first_document == "<p>LETTER-A</p>"
    postal_proxy.first_document = "<p>UPDATED</p>"
    postal_proxy.save(update_fields=["body_rich"])
    letter.refresh_from_db()
    assert letter.body_rich == "<p>UPDATED</p>"


def test_one_recipient_can_be_selected_on_two_steps_of_the_same_type():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite", subject="Invite", body_text="INVITE-BODY")
    reminder = _step(campaign, 2, MissiveType.EMAIL, "Reminder", subject="Reminder", body_text="REMINDER-BODY")
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])

    assert select(campaign, "email", ada, campaign_step=invite) == 1
    assert select(campaign, "email", ada, campaign_step=reminder) == 1
    assert CampaignTarget.objects.filter(campaign=campaign, campaign_step=invite).count() == 1
    assert CampaignTarget.objects.filter(campaign=campaign, campaign_step=reminder).count() == 1

    first, created_first = materialize_missive(
        campaign, ada, "email", build=build_campaign_contact, campaign_step=invite
    )
    second, created_second = materialize_missive(
        campaign, ada, "email", build=build_campaign_contact, campaign_step=reminder
    )

    assert created_first and created_second
    assert first.pk != second.pk
    assert first.campaign_step_id == invite.pk
    assert second.campaign_step_id == reminder.pk
    assert first.get_locally_or_campaign_value("body_text") == "INVITE-BODY"
    assert second.get_locally_or_campaign_value("body_text") == "REMINDER-BODY"

    existing = CampaignTarget.objects.get(campaign_step=invite)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CampaignTarget.objects.create(
                campaign=campaign,
                campaign_step=invite,
                missive_type=MissiveType.EMAIL,
                content_type_id=existing.content_type_id,
                object_id=existing.object_id,
            )


def test_send_order_follows_step_position_and_survives_an_interruption():
    campaign = _campaign()
    third = _step(campaign, 3, MissiveType.EMAIL, "Third", body_text="three")
    first = _step(campaign, 1, MissiveType.EMAIL, "First", body_text="one")
    second = _step(campaign, 2, MissiveType.EMAIL, "Second", body_text="two")
    late = _missive(campaign, third, MissiveType.EMAIL)
    early = _missive(campaign, first, MissiveType.EMAIL)
    middle = _missive(campaign, second, MissiveType.EMAIL)
    sched = MissiveScheduledCampaign.objects.create(campaign=campaign)
    Missive.objects.filter(pk__in=[late.pk, early.pk, middle.pk]).update(scheduler=sched)

    order = list(sched.get_missives().values_list("campaign_step_id", flat=True))
    assert order == [first.pk, second.pk, third.pk]

    early.status = MissiveStatus.SUCCESS
    early.save(update_fields=["status"])
    remaining = list(sched.get_missives().values_list("pk", flat=True))
    assert remaining == [middle.pk, late.pk]
    assert Missive.objects.get(pk=middle.pk).campaign_step_id == second.pk


def test_a_failed_step_does_not_block_the_next_one():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite", subject="Invite", body_text="INVITE-BODY")
    reminder = _step(campaign, 2, MissiveType.EMAIL, "Reminder", subject="Reminder", body_text="REMINDER-BODY")
    ada = create_campaign_contact("Ada", "Lovelace", emails=["ada@example.com"])
    select(campaign, "email", ada, campaign_step=invite)
    select(campaign, "email", ada, campaign_step=reminder)
    sched = MissiveScheduledCampaign.objects.create(
        campaign=campaign,
        send_date=timezone.now(),
        additional_config={"missive_types": ["email"]},
    )
    calls = []

    def send(self, **kwargs):
        calls.append(self.campaign_step_id)
        if self.campaign_step_id == invite.pk:
            raise RuntimeError("invite failed")
        self.status = MissiveStatus.SUCCESS
        self.save(update_fields=["status"])

    with patch.object(Missive, "send_missive", send):
        run_selection(sched.pk)

    assert calls == [invite.pk, reminder.pk]
    invite_missive = Missive.objects.get(campaign_step=invite)
    reminder_missive = Missive.objects.get(campaign_step=reminder)
    assert invite_missive.status == MissiveStatus.ERROR
    assert reminder_missive.status == MissiveStatus.SUCCESS


def test_retry_keeps_the_step_of_the_failed_missive():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite")
    failed = _missive(campaign, invite, MissiveType.EMAIL)
    failed.status = MissiveStatus.ERROR
    failed.save(update_fields=["status"])
    sched = MissiveScheduledCampaign.objects.create(campaign=campaign, retry_failed=True)

    assert sched._retry_error_missives() == 1

    draft = Missive.objects.get(campaign_step=invite, status=MissiveStatus.DRAFT, thread_type="missive")
    assert draft.pk != failed.pk
    assert draft.campaign_step_id == invite.pk
    failed.refresh_from_db()
    assert failed.thread_type == "history"


def test_a_file_can_belong_to_an_email_and_not_to_a_letter():
    campaign = _campaign()
    email = _step(campaign, 1, MissiveType.EMAIL, "Email")
    letter = _step(campaign, 2, MissiveType.LETTER, "Letter")
    shared_left = _file(campaign, "left.txt")
    only_email = _file(campaign, "email-only.txt")
    global_file = _file(campaign, "global.txt")
    only_email.campaign_step.add(email)
    shared_left.campaign_step.add(email)

    email_missive = _missive(campaign, email, MissiveType.EMAIL)
    letter_missive = _missive(campaign, letter, MissiveType.LETTER)
    email_ids = list(email_missive.attachments.values_list("pk", flat=True))
    letter_ids = list(letter_missive.attachments.values_list("pk", flat=True))

    assert email_ids == [shared_left.pk, only_email.pk, global_file.pk]
    assert only_email.pk not in letter_ids
    assert shared_left.pk not in letter_ids
    assert global_file.pk in letter_ids


def test_two_emails_can_share_files_in_campaign_priority_order():
    campaign = _campaign()
    first = _step(campaign, 1, MissiveType.EMAIL, "First")
    second = _step(campaign, 2, MissiveType.EMAIL, "Second")
    alpha = _file(campaign, "alpha.txt")
    beta = _file(campaign, "beta.txt")
    alpha.campaign_step.add(first, second)
    beta.campaign_step.add(first, second)

    first_ids = list(_missive(campaign, first, MissiveType.EMAIL).attachments.values_list("pk", flat=True))
    second_ids = list(_missive(campaign, second, MissiveType.EMAIL).attachments.values_list("pk", flat=True))

    assert first_ids == [alpha.pk, beta.pk]
    assert second_ids == [alpha.pk, beta.pk]
    assert set(first.attachments.values_list("pk", flat=True)) == {alpha.pk, beta.pk}


def test_campaign_step_relation_is_declared_on_attachments():
    field = MissiveBaseAttachment._meta.get_field("campaign_step")

    assert field.many_to_many is True
    assert "attachments" not in {field.name for field in CampaignStep._meta.local_many_to_many}


def test_branded_steps_do_not_reuse_phone_fields():
    campaign = _campaign()
    phone = _step(campaign, 1, MissiveType.SMS, "SMS", body_text="PHONE-STEP")
    branded = _step(
        campaign,
        2,
        MissiveType.BRANDED,
        "Discord",
        brand_name="Octolo",
        body_text="BRAND-STEP",
    )

    names = {field.name for field in BrandedCampaignStep._meta.fields}
    assert BrandedCampaignStep._meta.proxy is True
    assert "brand_name" in names

    sms = _missive(campaign, phone, MissiveType.SMS)
    app = _missive(campaign, branded, MissiveType.BRANDED)

    assert sms.get_locally_or_campaign_value("body_text") == "PHONE-STEP"
    assert app.get_locally_or_campaign_value("body_text") == "BRAND-STEP"
    assert app.get_locally_or_campaign_value("brand_name") == "Octolo"


def test_snapshot_records_the_ordered_steps_and_their_files():
    campaign = _campaign()
    _step(
        campaign,
        2,
        MissiveType.LETTER,
        "Letter",
        body_rich="<p>LETTER</p>",
        color_printing=True,
    )
    first = _step(campaign, 1, MissiveType.EMAIL, "Email", subject="Hello", body_text="EMAIL-BODY")
    alpha = _file(campaign, "alpha.txt")
    beta = _file(campaign, "beta.txt")
    alpha.campaign_step.add(first)
    beta.campaign_step.add(first)

    snap = campaign.to_snapshot()

    assert snap["version"] == 1
    assert snap["campaign"]["subject"] == "Launch"
    assert [step["position"] for step in snap["steps"]] == [1, 2]
    assert snap["steps"][0]["missive_type"] == MissiveType.EMAIL
    assert snap["steps"][0]["config"]["body_text"] == "EMAIL-BODY"
    assert snap["steps"][0]["attachments"] == [
        {"id": str(alpha.pk), "position": 1},
        {"id": str(beta.pk), "position": 2},
    ]
    assert snap["steps"][1]["config"]["color_printing"] is True
    assert campaign_from_snapshot(snap)["subject"] == "Launch"


def test_preview_is_identified_by_the_step():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite", subject="Invite", body_text="INVITE-BODY")
    _step(campaign, 2, MissiveType.EMAIL, "Reminder", subject="Reminder", body_text="REMINDER-BODY")
    url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])

    response = Client().get(url, {"step": invite.pk})

    assert response.status_code == 200
    html = response.content.decode()
    assert "INVITE-BODY" in html
    assert "REMINDER-BODY" not in html
    assert "1. Invite" in html


def test_channel_fields_only_exist_on_steps_and_old_snapshots_stay_readable():
    campaign = _campaign()
    campaign_fields = {field.name for field in MissiveCampaign._meta.fields}

    assert "email_body_text" not in campaign_fields
    assert "phone_body_text" not in campaign_fields
    assert "first_document" not in campaign_fields
    assert campaign_from_snapshot({"subject": "Old", "email_body_text": "Hi"}) == {
        "subject": "Old",
        "email_body_text": "Hi",
    }

    snap = campaign.to_snapshot()
    assert snap["version"] == 1
    assert snap["steps"] == []
    assert "email_body_text" not in campaign_from_snapshot(snap)


def test_progress_is_available_per_step_and_per_type():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite")
    reminder = _step(campaign, 2, MissiveType.EMAIL, "Reminder")
    sent = _missive(campaign, invite, MissiveType.EMAIL)
    sent.status = MissiveStatus.SUCCESS
    sent.save(update_fields=["status"])
    _missive(campaign, reminder, MissiveType.EMAIL)

    payload = campaign.progress_payload()

    assert payload["by_type"][MissiveType.EMAIL]["total"] == 2
    assert payload["by_type"][MissiveType.EMAIL]["sent"] == 1
    assert [step["label"] for step in payload["by_step"]] == ["Invite", "Reminder"]
    assert payload["by_step"][0]["sent"] == 1
    assert payload["by_step"][1]["total"] == 1
    assert payload["by_step"][1]["sent"] == 0

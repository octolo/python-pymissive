"""Campaigns composed of ordered, typed steps."""

from __future__ import annotations

import json
from collections.abc import Mapping
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.forms.formsets import DELETION_FIELD_NAME
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django_pymissive.models.attachment import MissiveBaseAttachment
from django_pymissive.models.campaign import MissiveCampaign, campaign_from_snapshot
from django_pymissive.models.campaign_step import (
    BrandedCampaignStep,
    CampaignStep,
    EmailCampaignStep,
    PhoneCampaignStep,
    PostalCampaignStep,
)
from django_pymissive.models.campaign_target import CampaignTarget
from django_pymissive.models.channel_config import (
    admin_missive_type_exclusions,
    admin_missive_type_fields,
    campaign_sourced_fields,
)
from django_pymissive.models.choices import (
    MissiveStatus,
    MissiveType,
)
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


def test_campaign_step_count_is_a_direct_total():
    campaign = _campaign()
    _step(campaign, 1, MissiveType.EMAIL)
    _step(campaign, 2, MissiveType.EMAIL)
    _step(campaign, 3, MissiveType.SMS)
    total = MissiveCampaign.objects.with_counts("count_step")

    annotated = total.get(pk=campaign.pk)
    detailed = MissiveCampaign.objects.with_counts(
        "count_step_email",
        "count_step_sms",
        "count_step",
    ).get(pk=campaign.pk)

    assert "count_step_email" not in total.query.annotations
    assert annotated.count_step == detailed.count_step == 3
    assert detailed.count_step_email == 2
    assert detailed.count_step_sms == 1


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
    )
    registered = _step(
        campaign,
        2,
        MissiveType.REGISTERED_LETTER,
        "Registered",
        body_rich="<p>LETTER-B</p>",
        duplex_printing=True,
        color_printing=False,
    )

    first = _missive(campaign, letter, MissiveType.LETTER)
    second = _missive(campaign, registered, MissiveType.REGISTERED_LETTER)

    assert first.get_locally_or_campaign_value("body_rich") == "<p>LETTER-A</p>"
    assert first.get_locally_or_campaign_value("duplex_printing") is False
    assert first.get_locally_or_campaign_value("color_printing") is True
    assert second.get_locally_or_campaign_value("body_rich") == "<p>LETTER-B</p>"
    assert second.get_locally_or_campaign_value("duplex_printing") is True
    assert second.get_locally_or_campaign_value("color_printing") is False

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


def test_building_one_step_does_not_reuse_the_other_steps_recipients():
    from django_pymissive.models.campaign_target import CampaignRecipientTarget
    from django_pymissive.models.choices import MissiveRecipientType
    from django_pymissive.processors.build_target import build_target_processor

    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite", subject="Invite", body_text="Invite")
    reminder = _step(campaign, 2, MissiveType.EMAIL, "Reminder", subject="Reminder", body_text="Reminder")
    ada = create_campaign_contact(
        "Ada",
        "Lovelace",
        emails=["ada@example.com", "ada.work@example.com"],
    )
    select(campaign, "email", ada, campaign_step=invite)
    CampaignRecipientTarget.objects.create(
        target=CampaignTarget.objects.get(campaign_step=invite),
        recipient_type=MissiveRecipientType.RECIPIENT,
        values=["only-invite@example.com"],
    )

    limited = build_target_processor(campaign, ada, "email", full_targets=True, campaign_step=reminder)
    opened = build_target_processor(campaign, ada, "email", full_targets=True, campaign_step=invite)

    assert limited.campaign_step_id == reminder.pk
    assert list(limited.to_missiverecipient.values_list("email", flat=True)) == [
        "ada@example.com",
        "ada.work@example.com",
    ]
    assert list(opened.to_missiverecipient.values_list("email", flat=True)) == ["only-invite@example.com"]

    existing = CampaignTarget.objects.get(campaign_step=invite)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CampaignTarget.objects.create(
                campaign=campaign,
                campaign_step=invite,
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


def test_deleting_a_step_does_not_share_its_private_files():
    campaign = _campaign()
    email = _step(campaign, 1, MissiveType.EMAIL, "Email")
    letter = _step(campaign, 2, MissiveType.LETTER, "Letter")
    only_email = _file(campaign, "email-only.txt")
    shared = _file(campaign, "shared.txt")
    untouched = _file(campaign, "global.txt")
    only_email.campaign_step.add(email)
    shared.campaign_step.add(email, letter)

    email.delete()

    assert not MissiveBaseAttachment.objects.filter(pk=only_email.pk).exists()
    shared.refresh_from_db()
    assert list(shared.campaign_step.values_list("pk", flat=True)) == [letter.pk]
    letter_ids = list(_missive(campaign, letter, MissiveType.LETTER).attachments.values_list("pk", flat=True))
    assert only_email.pk not in letter_ids
    assert shared.pk in letter_ids
    assert untouched.pk in letter_ids


def test_deleting_every_step_of_a_file_does_not_share_it():
    campaign = _campaign()
    email = _step(campaign, 1, MissiveType.EMAIL, "Email")
    sms = _step(campaign, 2, MissiveType.SMS, "Text")
    letter = _step(campaign, 3, MissiveType.LETTER, "Letter")
    both = _file(campaign, "both.txt")
    kept = _file(campaign, "kept.txt")
    untouched = _file(campaign, "global.txt")
    both.campaign_step.add(email, sms)
    kept.campaign_step.add(email, sms, letter)

    CampaignStep.objects.filter(pk__in=[email.pk, sms.pk]).delete()

    assert not MissiveBaseAttachment.objects.filter(pk=both.pk).exists()
    assert list(kept.campaign_step.values_list("pk", flat=True)) == [letter.pk]
    letter_ids = list(_missive(campaign, letter, MissiveType.LETTER).attachments.values_list("pk", flat=True))
    assert both.pk not in letter_ids
    assert kept.pk in letter_ids
    assert untouched.pk in letter_ids


def test_deleting_a_typed_step_does_not_share_its_private_file():
    campaign = _campaign()
    email = _step(campaign, 1, MissiveType.EMAIL, "Email")
    letter = _step(campaign, 2, MissiveType.LETTER, "Letter")
    only_email = _file(campaign, "email-only.txt")
    untouched = _file(campaign, "global.txt")
    only_email.campaign_step.add(email)

    EmailCampaignStep.objects.get(pk=email.pk).delete()

    assert not MissiveBaseAttachment.objects.filter(pk=only_email.pk).exists()
    letter_ids = list(_missive(campaign, letter, MissiveType.LETTER).attachments.values_list("pk", flat=True))
    assert only_email.pk not in letter_ids
    assert untouched.pk in letter_ids


def test_a_step_with_only_drafts_can_be_deleted():
    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.EMAIL)
    draft = _missive(campaign, step, MissiveType.EMAIL)

    step.delete()

    assert not CampaignStep.objects.filter(pk=step.pk).exists()
    draft.refresh_from_db()
    assert draft.campaign_step_id is None


def test_a_step_that_sent_a_missive_cannot_be_deleted():
    campaign = _campaign()
    sent_step = _step(campaign, 1, MissiveType.EMAIL, "Invite")
    draft_step = _step(campaign, 2, MissiveType.SMS, "Text")
    sent = _missive(campaign, sent_step, MissiveType.EMAIL)
    sent.status = MissiveStatus.SUCCESS
    sent.save(update_fields=["status"])
    draft = _missive(campaign, draft_step, MissiveType.SMS)

    with pytest.raises(ProtectedError, match="left the draft state"):
        sent_step.delete()
    with pytest.raises(ProtectedError, match="left the draft state"):
        CampaignStep.objects.filter(pk=sent_step.pk).delete()

    assert CampaignStep.objects.filter(pk=sent_step.pk).exists()
    sent.refresh_from_db()
    assert sent.campaign_step_id == sent_step.pk
    draft_step.delete()
    assert not CampaignStep.objects.filter(pk=draft_step.pk).exists()
    draft.refresh_from_db()
    assert draft.campaign_step_id is None


def test_step_admin_hides_delete_once_a_missive_left_draft():
    from django.contrib.auth import get_user_model

    from django_pymissive.admin.campaign_step import EmailCampaignStepInline

    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.EMAIL, "Invite")
    sent = _missive(campaign, step, MissiveType.EMAIL)
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        username="step-delete",
        email="step-delete@example.com",
        password="x",
    )
    step_admin = admin.site._registry[CampaignStep]

    assert step_admin.has_delete_permission(request, step) is True

    sent.status = MissiveStatus.SUCCESS
    sent.save(update_fields=["status"])

    assert step_admin.has_delete_permission(request, CampaignStep.objects.get(pk=step.pk)) is False
    inline = EmailCampaignStepInline(MissiveCampaign, admin.site)
    formset = inline.get_formset(request, campaign)(instance=campaign)
    assert DELETION_FIELD_NAME not in formset.forms[0].fields


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


def test_campaign_step_type_proxy_forces_and_filters_its_exact_type():
    from django_pymissive.models.campaign_step import RcsCampaignStep

    campaign = _campaign()
    _step(campaign, 1, MissiveType.SMS, "SMS")
    rcs = RcsCampaignStep(campaign=campaign, position=2, missive_type=MissiveType.EMAIL, label="RCS")

    rcs.save()

    assert rcs.missive_type == MissiveType.RCS
    assert list(RcsCampaignStep.objects.values_list("pk", flat=True)) == [rcs.pk]


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


def test_campaign_step_has_its_own_preview_url():
    from django.contrib.auth import get_user_model

    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.EMAIL, "Invite", body_text="INVITE-BODY")
    expected_url = reverse("django_pymissive:preview_campaign_step", args=[step.pk])
    client = Client()
    client.force_login(
        get_user_model().objects.create_superuser(
            username="step-preview",
            email="step-preview@example.com",
            password="x",
        )
    )

    response = client.get(step.get_browser_preview_path())

    assert step.get_browser_preview_path() == expected_url
    assert response.status_code == 200
    assert "INVITE-BODY" in response.content.decode()


def test_campaign_admin_preview_links_to_its_filtered_step_list():
    from django.contrib.auth import get_user_model
    from django_pymissive.admin.campaign import MissiveCampaignAdmin
    from django_pymissive.admin.campaign_step import CampaignStepAdmin

    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.EMAIL, "Invite")
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        username="campaign-preview-list",
        email="campaign-preview-list@example.com",
        password="x",
    )

    campaign_admin = MissiveCampaignAdmin(MissiveCampaign, admin.site)
    step_admin = CampaignStepAdmin(CampaignStep, admin.site)
    step_list_url = reverse("admin:django_pymissive_campaignstep_changelist")

    response = campaign_admin.handle_preview(request, str(campaign.pk))
    client = Client()
    client.force_login(request.user)
    step_list = client.get(step_list_url, {"campaign__id__exact": campaign.pk})
    target_list = client.get(
        reverse("admin:django_pymissive_campaigntarget_changelist"),
        {"campaign_step__id__exact": step.pk, "state": "pending"},
    )

    assert response.status_code == 302
    assert response.url == f"{step_list_url}?campaign__id__exact={campaign.pk}"
    assert step_list.status_code == 200
    assert target_list.status_code == 200
    assert list(step_list.context["cl"].queryset) == [step]
    first_column = str(step_admin.position_type_display(step))
    content = step_list.content.decode()
    assert f"1. {step.get_missive_type_display()}" in first_column
    assert campaign.subject in first_column
    assert f"1. {step.get_missive_type_display()}" in content
    assert campaign.subject in content
    assert "0 missive(s)" in content
    assert "0 pending" in content
    assert step.get_browser_preview_path() in content
    assert step.get_browser_preview_path() in str(step_admin.preview_display(step))


def test_campaign_preview_requires_a_step_when_the_channel_is_ambiguous():
    campaign = _campaign()
    invite = _step(campaign, 1, MissiveType.EMAIL, "Invite", body_text="INVITE-BODY")
    _step(campaign, 2, MissiveType.EMAIL, "Reminder", body_text="REMINDER-BODY")
    url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])

    assert Client().get(url, {"type": "email"}).status_code == 404
    assert Client().get(url, {"type": "email", "step": invite.pk}).status_code == 200


def test_campaign_preview_rejects_a_step_from_another_campaign():
    campaign = _campaign()
    other_campaign = _campaign()
    foreign_step = _step(other_campaign, 1, MissiveType.EMAIL, "Foreign", body_text="FOREIGN")
    url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])

    assert Client().get(url, {"type": "email", "step": foreign_step.pk}).status_code == 404


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


_PARIS = {
    "address_line1": "1 rue de la Paix",
    "postal_code": "75002",
    "city": "Paris",
    "country": "France",
}
_LYON = {
    "address_line1": "2 place Bellecour",
    "postal_code": "69002",
    "city": "Lyon",
    "country": "France",
}
_NANTES = {
    "address_line1": "3 cours des 50 Otages",
    "postal_code": "44000",
    "city": "Nantes",
    "country": "France",
}
_STEP_VALUES = {
    "subject": "Step subject",
    "body_rich": "<p>step</p>",
    "body_rich_snapshot_html": "<p>step snapshot</p>",
    "body_text": "step text",
    "sender_name": "Step Sender",
    "sender_email": "step@example.com",
    "reply_to_name": "Step Reply",
    "reply_to_email": "reply-step@example.com",
    "sender_phone": "+33611111111",
    "brand_name": "step-brand",
    "sender_address": _PARIS,
    "reply_to_address": _PARIS,
}
_LOCAL_VALUES = {
    "subject": "Local subject",
    "body_rich": "<p>local</p>",
    "body_rich_snapshot_html": "<p>local snapshot</p>",
    "body_text": "local text",
    "sender_name": "Local Sender",
    "sender_email": "local@example.com",
    "reply_to_name": "Local Reply",
    "reply_to_email": "reply-local@example.com",
    "sender_phone": "+33622222222",
    "brand_name": "local-brand",
    "sender_address": _LYON,
    "reply_to_address": _LYON,
}
_RESYNC_VALUES = {
    "subject": "Resync subject",
    "body_rich": "<p>resync</p>",
    "body_rich_snapshot_html": "<p>resync snapshot</p>",
    "body_text": "resync text",
    "sender_name": "Resync Sender",
    "sender_email": "resync@example.com",
    "reply_to_name": "Resync Reply",
    "reply_to_email": "reply-resync@example.com",
    "sender_phone": "+33633333333",
    "brand_name": "resync-brand",
    "sender_address": _NANTES,
    "reply_to_address": _NANTES,
}
_SUPPORTS = [
    ("email", MissiveType.EMAIL),
    ("phone", MissiveType.SMS),
    ("application", MissiveType.BRANDED),
    ("address", MissiveType.LETTER),
]
_ADMIN_CONTENT_FIELDS = {
    MissiveType.EMAIL: [
        "subject",
        "sender_name",
        "sender_email",
        "reply_to_name",
        "reply_to_email",
        "body_text",
        "body_rich",
        "body_rich_snapshot_html",
    ],
    MissiveType.SMS: ["sender_name", "sender_phone", "body_text"],
    MissiveType.LETTER: [
        "sender_name",
        "sender_address",
        "reply_to_name",
        "reply_to_address",
        "duplex_printing",
        "color_printing",
        "body_rich",
        "body_rich_snapshot_html",
    ],
    MissiveType.BRANDED: [
        "brand_name",
        "subject",
        "sender_name",
        "body_text",
        "body_rich",
        "body_rich_snapshot_html",
    ],
}
_ADMIN_CONTENT_FIELDS.update(
    {
        missive_type: list(_ADMIN_CONTENT_FIELDS[MissiveType.EMAIL])
        for missive_type in (MissiveType.EMAIL_MARKETING, MissiveType.ERE)
    }
)
_ADMIN_CONTENT_FIELDS.update(
    {
        missive_type: list(_ADMIN_CONTENT_FIELDS[MissiveType.SMS])
        for missive_type in (MissiveType.RCS, MissiveType.VOICE_CALL)
    }
)
_ADMIN_CONTENT_FIELDS.update(
    {
        missive_type: list(_ADMIN_CONTENT_FIELDS[MissiveType.LETTER])
        for missive_type in (MissiveType.REGISTERED_LETTER, MissiveType.HAND_DELIVERY)
    }
)
_ADMIN_CONTENT_FIELDS.update(
    {
        missive_type: ["subject", "sender_name", "body_text", "body_rich", "body_rich_snapshot_html"]
        for missive_type in (MissiveType.NOTIFICATION, MissiveType.PUSH_NOTIFICATION)
    }
)
_ADMIN_TYPES = [
    (MissiveType.EMAIL, "email"),
    (MissiveType.EMAIL_MARKETING, "email"),
    (MissiveType.ERE, "email"),
    (MissiveType.SMS, "phone"),
    (MissiveType.RCS, "phone"),
    (MissiveType.VOICE_CALL, "phone"),
    (MissiveType.LETTER, "address"),
    (MissiveType.REGISTERED_LETTER, "address"),
    (MissiveType.HAND_DELIVERY, "address"),
    (MissiveType.NOTIFICATION, "application"),
    (MissiveType.PUSH_NOTIFICATION, "application"),
    (MissiveType.BRANDED, "application"),
]


def _same(left, right) -> bool:
    if hasattr(left, "as_e164") or hasattr(right, "as_e164"):
        return str(left or "") == str(right or "")
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return dict(left) == dict(right)
    return left == right


def _values(names, source):
    return {name: source[name] for name in names}


@pytest.mark.parametrize("support,missive_type", _SUPPORTS)
@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_sourced_fields_resolve_copy_resync_and_clear(support, missive_type):
    names = [name for name in campaign_sourced_fields(support) if name not in {"duplex_printing", "color_printing"}]
    campaign = _campaign()
    step = _step(campaign, 1, missive_type, **_values(names, _STEP_VALUES))
    inherited = _missive(campaign, step, missive_type)
    local = Missive.objects.create(
        campaign_step=step,
        missive_type=missive_type,
        status=MissiveStatus.DRAFT,
        **_values(names, _LOCAL_VALUES),
    )

    for name in names:
        assert _same(inherited.get_locally_or_campaign_value(name), getattr(step, name))
        assert _same(local.get_locally_or_campaign_value(name), getattr(local, name))
        assert not _same(getattr(local, name), getattr(step, name))

    inherited.set_locally_ifnull()
    inherited.refresh_from_db()
    for name in names:
        assert _same(getattr(inherited, name), getattr(step, name))

    for name, value in _values(names, _RESYNC_VALUES).items():
        setattr(step, name, value)
    step.save(update_fields=names)
    step.refresh_from_db()
    inherited = Missive.objects.get(pk=inherited.pk)
    inherited.apply_campaign_config(inherited)
    inherited.refresh_from_db()
    for name in names:
        assert _same(getattr(inherited, name), getattr(step, name))

    inherited.clear_campaign_sourced_fields(inherited)
    inherited.refresh_from_db()
    for name in names:
        field = inherited._meta.get_field(name)
        expected = None if field.null else field.get_default()
        assert _same(getattr(inherited, name), expected)
    assert inherited.additional_context == {}


@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_step_false_duplex_and_true_color_are_copied_then_cleared():
    campaign = _campaign()
    step = _step(
        campaign,
        1,
        MissiveType.LETTER,
        duplex_printing=False,
        color_printing=True,
    )
    missive = _missive(campaign, step, MissiveType.LETTER)

    assert missive.duplex_printing is True
    assert missive.color_printing is False
    assert missive.get_locally_or_campaign_value("duplex_printing") is False
    assert missive.get_locally_or_campaign_value("color_printing") is True

    missive.set_locally_ifnull()
    missive.refresh_from_db()
    assert missive.duplex_printing is False
    assert missive.color_printing is True

    step.duplex_printing = True
    step.color_printing = False
    step.save(update_fields=["duplex_printing", "color_printing"])
    missive = Missive.objects.get(pk=missive.pk)
    missive.apply_campaign_config(missive)
    missive.refresh_from_db()
    assert missive.duplex_printing is True
    assert missive.color_printing is False

    missive.clear_campaign_sourced_fields(missive)
    missive.refresh_from_db()
    assert missive.duplex_printing is True
    assert missive.color_printing is False


@override_settings(PYMISSIVE_DEFAULT_SENDER={})
def test_explicit_boolean_overrides_step_and_absent_step_keeps_local_values():
    campaign = _campaign()
    step = _step(campaign, 1, MissiveType.LETTER, duplex_printing=True, color_printing=False)
    linked = _missive(campaign, step, MissiveType.LETTER)
    linked.duplex_printing = False
    linked.color_printing = True

    assert linked.get_locally_or_campaign_value("duplex_printing") is False
    assert linked.get_locally_or_campaign_value("color_printing") is True

    standalone = Missive.objects.create(missive_type=MissiveType.LETTER, subject="Alone")
    standalone.subject = "Kept"
    standalone.duplex_printing = False
    standalone.clear_campaign_sourced_fields(standalone)

    assert standalone.campaign_step_id is None
    assert standalone.get_locally_or_campaign_value("duplex_printing") is False
    assert standalone.get_locally_or_campaign_value("color_printing") is False
    assert standalone.subject == "Kept"
    assert standalone.duplex_printing is False


def test_campaign_sourced_fields_returns_an_independent_list():
    fields = campaign_sourced_fields("email")
    fields.append("status")
    assert "status" not in campaign_sourced_fields("email")
    assert campaign_sourced_fields("unknown") == []


def test_snapshot_round_trip_keeps_the_full_document():
    campaign = _campaign(metadata={"note": "frozen"})
    step = _step(
        campaign,
        1,
        MissiveType.EMAIL,
        "Email",
        subject="Hello",
        body_text="BODY",
        build_target_processors=["myapp.build"],
    )
    snap = campaign.to_snapshot()

    assert json.loads(json.dumps(snap)) == snap
    assert set(snap) == {"version", "campaign", "steps"}
    assert snap["campaign"]["metadata"] == {"note": "frozen"}
    step_snap = snap["steps"][0]
    assert set(step_snap) == {
        "id",
        "position",
        "label",
        "missive_type",
        "build_target_processors",
        "config",
        "attachments",
    }
    assert step_snap["id"] == step.pk
    assert step_snap["config"]["subject"] == "Hello"
    assert step_snap["config"]["body_text"] == "BODY"
    assert "id" not in step_snap["config"]
    assert "campaign_id" not in step_snap["config"]
    assert "position" not in step_snap["config"]
    assert "build_target_processors" not in step_snap["config"]


def test_campaign_admin_splits_steps_into_one_inline_per_missive_type():
    from django.contrib.auth import get_user_model
    from django.contrib.admin.utils import flatten_fieldsets

    from django_pymissive.admin.campaign_step import (
        BrandedCampaignStepInline,
        EmailCampaignStepInline,
        EmailMarketingCampaignStepInline,
        EreCampaignStepInline,
        HandDeliveryCampaignStepInline,
        LetterCampaignStepInline,
        NotificationCampaignStepInline,
        PushNotificationCampaignStepInline,
        RcsCampaignStepInline,
        RegisteredLetterCampaignStepInline,
        SmsCampaignStepInline,
        VoiceCallCampaignStepInline,
    )

    campaign = _campaign()
    inline_types = [
        (LetterCampaignStepInline, MissiveType.LETTER),
        (RegisteredLetterCampaignStepInline, MissiveType.REGISTERED_LETTER),
        (HandDeliveryCampaignStepInline, MissiveType.HAND_DELIVERY),
        (EreCampaignStepInline, MissiveType.ERE),
        (EmailCampaignStepInline, MissiveType.EMAIL),
        (EmailMarketingCampaignStepInline, MissiveType.EMAIL_MARKETING),
        (SmsCampaignStepInline, MissiveType.SMS),
        (RcsCampaignStepInline, MissiveType.RCS),
        (VoiceCallCampaignStepInline, MissiveType.VOICE_CALL),
        (NotificationCampaignStepInline, MissiveType.NOTIFICATION),
        (PushNotificationCampaignStepInline, MissiveType.PUSH_NOTIFICATION),
        (BrandedCampaignStepInline, MissiveType.BRANDED),
    ]
    expected = {
        inline_cls: _step(campaign, position, missive_type, str(missive_type)).pk
        for position, (inline_cls, missive_type) in enumerate(inline_types, start=1)
    }
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(username="steps", email="steps@example.com", password="x")
    inlines = admin.site._registry[MissiveCampaign].get_inline_instances(request, campaign)
    by_type = {type(inline): inline for inline in inlines}

    assert [type(inline) for inline in inlines[:12]] == list(expected)
    formsets, _inline_instances = admin.site._registry[MissiveCampaign]._create_formsets(request, campaign, change=True)
    assert len({formset.prefix for formset in formsets[:12]}) == 12
    for inline_cls, pk, formset in zip(expected, expected.values(), formsets[:12], strict=True):
        inline = by_type[inline_cls]
        assert list(formset.get_queryset().values_list("pk", flat=True)) == [pk]
        assert flatten_fieldsets(inline.get_fieldsets(request, campaign)) == [
            "position",
            "label",
            *_ADMIN_CONTENT_FIELDS[inline.missive_type],
        ]
        assert "missive_type" not in formset.form.base_fields


def test_campaign_admin_only_shows_active_step_inlines_without_direct_add():
    from django.contrib.auth import get_user_model

    from django_pymissive.admin.campaign_step import CampaignStepInline, EmailCampaignStepInline

    campaign = _campaign()
    _step(campaign, 1, MissiveType.EMAIL, "Email")
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        username="active-steps",
        email="active-steps@example.com",
        password="x",
    )

    inlines = admin.site._registry[MissiveCampaign].get_inline_instances(request, campaign)
    step_inlines = [inline for inline in inlines if isinstance(inline, CampaignStepInline)]

    assert [type(inline) for inline in step_inlines] == [EmailCampaignStepInline]
    assert step_inlines[0].has_add_permission(request, campaign) is False


def test_campaign_admin_only_shows_scheduler_inline_when_steps_exist():
    from django.contrib.auth import get_user_model

    from django_pymissive.admin.scheduler import MissiveScheduledCampaignInline

    campaign = _campaign()
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        username="scheduler-inline",
        email="scheduler-inline@example.com",
        password="x",
    )
    model_admin = admin.site._registry[MissiveCampaign]

    assert not any(
        isinstance(inline, MissiveScheduledCampaignInline)
        for inline in model_admin.get_inline_instances(request, campaign)
    )

    _step(campaign, 1, MissiveType.EMAIL, "Email")

    inlines = model_admin.get_inline_instances(request, campaign)
    assert isinstance(inlines[-1], MissiveScheduledCampaignInline)


def test_campaign_step_add_view_selects_type_then_saves_the_proxy_form():
    from django.contrib.auth import get_user_model

    campaign = _campaign()
    user = get_user_model().objects.create_superuser(
        username="add-step",
        email="add-step@example.com",
        password="x",
    )
    client = Client()
    client.force_login(user)
    url = reverse(
        "admin:django_pymissive_missivecampaign_add_campaign_step",
        args=[campaign.pk],
    )

    chooser = client.get(url)
    selected = client.post(url, {"missive_type": MissiveType.LETTER})
    form_page = client.get(url, {"missive_type": MissiveType.LETTER})

    assert chooser.status_code == 200
    assert list(chooser.context["adminform"].form.fields) == ["missive_type"]
    assert selected.status_code == 302
    assert selected.url == f"{url}?missive_type=letter"
    fields = form_page.context["adminform"].form.fields
    assert "missive_type" not in fields
    assert "subject" not in fields
    assert "color_printing" in fields
    assert "body_rich" in fields
    assert "body_rich_snapshot_html" not in fields
    assert ("position", "label") in form_page.context["adminform"].fieldsets[0][1]["fields"]
    assert ("sender_name", "sender_address") in form_page.context["adminform"].fieldsets[1][1]["fields"]
    assert ("reply_to_name", "reply_to_address") in form_page.context["adminform"].fieldsets[1][1]["fields"]

    saved = client.post(
        f"{url}?missive_type=letter",
        {
            "position": "1",
            "label": "Postal",
        },
    )

    assert saved.status_code == 302
    step = campaign.to_campaignstep.get()
    assert step.missive_type == MissiveType.LETTER
    assert step.label == "Postal"


@pytest.mark.parametrize("missive_type,support", _ADMIN_TYPES)
def test_campaign_step_admin_keeps_the_channel_form(missive_type, support):
    from django.contrib.admin.utils import flatten_fieldsets

    assert EmailCampaignStep not in admin.site._registry
    assert PhoneCampaignStep not in admin.site._registry
    assert PostalCampaignStep not in admin.site._registry
    assert BrandedCampaignStep not in admin.site._registry
    model_admin = admin.site._registry[CampaignStep]
    step = CampaignStep(missive_type=missive_type)
    fieldsets = model_admin.get_fieldsets(RequestFactory().get("/"), step)
    shown = flatten_fieldsets([fieldsets[1]])

    assert str(fieldsets[1][0]) == "Content"
    assert str(fieldsets[2][0]) == "Configuration"
    assert list(fieldsets[0][1]["fields"]) == ["campaign", ("position", "label"), "missive_type"]
    assert shown == _ADMIN_CONTENT_FIELDS[missive_type]
    assert shown == admin_missive_type_fields(missive_type)
    assert list(fieldsets[2][1]["fields"]) == [
        "metadata",
        "additional_context",
        "additional_config",
        "body_processors",
        "first_document_processors",
        "attachment_processors",
        "build_target_processors",
    ]
    excluded = set(admin_missive_type_exclusions(missive_type))
    assert set(campaign_sourced_fields(support)) - set(shown) == excluded
    assert set(shown) <= set(campaign_sourced_fields(support))
    assert "body_rich_snapshot_html" in model_admin.get_readonly_fields(RequestFactory().get("/"), step)
    if support == "address":
        form = model_admin.get_form(RequestFactory().get("/"), step)
        assert str(form.base_fields["body_rich"].label) == "First document"


def test_all_html_snapshots_are_readonly_in_admin():
    request = RequestFactory().get("/")

    assert "description_snapshot_html" in admin.site._registry[MissiveCampaign].get_readonly_fields(request)
    assert "body_rich_snapshot_html" in admin.site._registry[Missive].get_readonly_fields(request)

"""A campaign target opens the same preview as a missive, without saving one."""

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from django.urls import reverse
from django_pymissive.models import CampaignStep, CampaignTarget, Missive, MissiveCampaign, MissiveStatus, MissiveType
from django_pymissive.models.choices import MissiveRecipientType
from django_pymissive.processors.build_target import ordered_target_contacts
from django_pymissive.services import select
from django_pymissive.services.preview import PreviewRecipient, PreviewRuntimeData, prepare_preview, resolve_preview

from tests.fakeapp.models import Contact

pytestmark = pytest.mark.django_db


def _campaign():
    campaign = MissiveCampaign.objects.create(subject="Assemblée")
    CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=MissiveType.EMAIL,
        subject="Assemblée",
        body_rich="<p>token-{{ contact.id }}-{{ step_token }}</p>",
        body_text="Bonjour",
        additional_context={"step_token": "from-step"},
    )
    return campaign


def _staff(username, *, view=True):
    user = get_user_model().objects.create_user(username=username, password="x", is_staff=True)
    if view:
        user.user_permissions.add(Permission.objects.get(codename="view_campaigntarget"))
        user = get_user_model().objects.get(pk=user.pk)
    return user


def _row():
    campaign = _campaign()
    step = campaign.to_campaignstep.get()
    contact = Contact.objects.create(first_name="Ada", last_name="Lovelace", email="ada-preview@example.com")
    select(campaign, "email", contact, campaign_step=step)
    return CampaignTarget.objects.get(campaign=campaign), contact


def test_target_preview_renders_the_contact_and_saves_nothing():
    row, contact = _row()
    row.add_recipient(
        {"name": "Grace", "email": "grace-preview@example.com"},
        recipient_type=MissiveRecipientType.CC,
    )
    user = _staff("preview-target")
    client = Client()
    client.force_login(user)

    response = client.get(reverse("django_pymissive:preview_target", args=[row.pk]))

    assert response.status_code == 200
    html = response.content.decode()
    assert f"token-{contact.pk}" in html
    assert "from-step" in html
    assert "ada-preview@example.com" in html
    assert "grace-preview@example.com" in html
    assert Missive.objects.count() == 0
    assert CampaignTarget.objects.get(pk=row.pk).missive_id is None


def test_target_resolver_uses_the_same_pure_contacts_as_generation():
    row, _contact = _row()
    row.add_recipient(
        {"name": "Grace", "email": "grace-preview@example.com"},
        recipient_type=MissiveRecipientType.CC,
    )

    expected = ordered_target_contacts(row)
    preview = resolve_preview(row)
    recipients = preview.runtime_data.recipients

    assert [(recipient.recipient_type, recipient.name, recipient.email) for recipient in recipients] == expected
    assert preview.runtime_data is preview.missive._preview_runtime
    assert preview.missive._state.adding
    assert Missive.objects.count() == 0


def test_prepare_preview_keeps_a_named_recipient_without_an_address():
    campaign = _campaign()
    step = campaign.to_campaignstep.get()

    preview = prepare_preview(
        campaign,
        step,
        recipients=[{"name": "Ada Lovelace", "recipient_type": MissiveRecipientType.RECIPIENT}],
    )

    recipient = preview.runtime_data.recipients[0]
    assert recipient.name == "Ada Lovelace"
    assert recipient.email == ""
    assert recipient.address is None
    assert preview.missive._state.adding
    assert Missive.objects.count() == 0


@override_settings(PYMISSIVE_ALLOWED_TASK_BACKENDS=None)
def test_prepare_preview_uses_the_target_contacts_until_a_processor_answers():
    row, _contact = _row()

    default = prepare_preview(row.campaign, row.campaign_step, row)
    assert [(item.recipient_type, item.name, item.email) for item in default.runtime_data.recipients] == (
        ordered_target_contacts(row)
    )

    def processor(campaign, step, target):
        assert target is row
        return {
            "subject": "Rendered",
            "recipients": [PreviewRecipient(recipient_type=MissiveRecipientType.RECIPIENT, name="Grace")],
            "related_objects": (target,),
        }

    prepared = prepare_preview(row.campaign, row.campaign_step, row, processors=[lambda *args: None, processor])
    assert prepared.missive.subject == "Rendered"
    assert prepared.runtime_data.recipients[0].name == "Grace"
    assert prepared.runtime_data.related_objects == (row,)
    assert Missive.objects.count() == 0

    dotted = prepare_preview(
        row.campaign,
        row.campaign_step,
        row,
        processors=["tests.test_target_preview._named_preview"],
    )
    assert dotted.runtime_data == PreviewRuntimeData(
        recipients=(PreviewRecipient(recipient_type=MissiveRecipientType.RECIPIENT, name="Named"),),
    )


def _named_preview(campaign, step, target):
    return PreviewRuntimeData(
        recipients=(PreviewRecipient(recipient_type=MissiveRecipientType.RECIPIENT, name="Named"),),
    )


def _subject_preview(campaign, step, target):
    return {"subject": "Configured preview"}


@override_settings(
    PYMISSIVE_ALLOWED_TASK_BACKENDS=None,
    PYMISSIVE_PREVIEW_PROCESSORS=["tests.test_target_preview._subject_preview"],
)
def test_resolve_preview_runs_the_configured_hook_and_keeps_default_recipients():
    row, _contact = _row()

    preview = resolve_preview(row)
    step_preview = resolve_preview(row.campaign_step)
    campaign_preview = resolve_preview(row.campaign, campaign_step=row.campaign_step)

    assert preview.missive.subject == "Configured preview"
    assert step_preview.missive.subject == "Configured preview"
    assert campaign_preview.missive.subject == "Configured preview"
    assert [(item.recipient_type, item.name, item.email) for item in preview.runtime_data.recipients] == (
        ordered_target_contacts(row)
    )


def test_prepare_preview_uses_the_step_channel_for_tuple_recipients():
    campaign = _campaign()
    sms_step = CampaignStep.objects.create(
        campaign=campaign,
        position=2,
        missive_type=MissiveType.SMS,
    )

    preview = prepare_preview(
        campaign,
        sms_step,
        recipients=[(MissiveRecipientType.RECIPIENT, "Ada", "+33601020304")],
        processors=[],
    )

    assert preview.runtime_data.recipients == (
        PreviewRecipient(
            recipient_type=MissiveRecipientType.RECIPIENT,
            name="Ada",
            phone="+33601020304",
        ),
    )


def test_target_preview_is_staff_only():
    row, _contact = _row()
    url = reverse("django_pymissive:preview_target", args=[row.pk])

    anonymous = Client().get(url)
    assert anonymous.status_code == 302
    assert "login" in anonymous.url

    client = Client()
    client.force_login(_staff("preview-no-right", view=False))
    assert client.get(url).status_code == 403


def test_target_with_a_missive_uses_that_preview():
    row, _contact = _row()
    missive = Missive.objects.create(
        campaign_step=row.campaign_step,
        missive_type=MissiveType.EMAIL,
        subject="Déjà rédigé",
        body_rich="<p>Déjà rédigé</p>",
        status=MissiveStatus.DRAFT,
    )
    row.attach_missive(missive)
    model_admin = admin.site._registry[CampaignTarget]

    assert row.get_browser_preview_path() == missive.get_browser_preview_path()
    assert model_admin.preview._admin_boost_config["view_type"] == "redirect"

    client = Client()
    client.force_login(_staff("preview-existing"))
    response = client.get(reverse("django_pymissive:preview_target", args=[row.pk]))

    assert response.status_code == 302
    assert response.url == missive.get_browser_preview_path()

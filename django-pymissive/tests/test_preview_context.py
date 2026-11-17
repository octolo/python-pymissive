"""``build_preview_context`` must not swallow a broken preview into ``{}``."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import MissiveRecipientType, MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from django_pymissive.services.preview import (
    PreviewRecipient,
    PreviewRuntimeData,
    build_preview_context,
    build_render_context,
    resolve_preview,
)
from django_pymissive.views.preview import (
    POSTAL_PREVIEW_MISSIVE_TYPES,
    missive_for_campaign_preview,
)

pytestmark = pytest.mark.django_db


def _email_missive(**kw) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "body_text": "Body",
        "sender_name": "Octolo",
        "sender_email": "hello@example.com",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kw)
    return Missive.objects.create(**defaults)


def test_email_context_lists_persisted_recipients():
    missive = _email_missive()
    MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Bob",
        email="bob@example.com",
        recipient_type=MissiveRecipientType.CC,
    )

    ctx = build_preview_context(missive)

    assert ctx["sender"]["email"] == "hello@example.com"
    assert ctx["to_recipients"] == [{"name": "Alice", "email": "alice@example.com"}]
    assert ctx["cc_recipients"] == [{"name": "Bob", "email": "bob@example.com"}]
    assert "notification_recipients" not in ctx


def test_email_context_ignores_notification_recipients():
    missive = _email_missive()
    MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Ops",
        email="ops@example.com",
        recipient_type=MissiveRecipientType.NOTIFICATION,
    )

    ctx = build_preview_context(missive)

    assert ctx["to_recipients"] == [{"name": "Alice", "email": "alice@example.com"}]
    assert ctx["cc_recipients"] == []
    assert ctx["bcc_recipients"] == []
    assert "notification_recipients" not in ctx


def test_unsaved_campaign_missive_skips_recipients_without_raising():
    campaign = MissiveCampaign.objects.create(subject="Campaign")
    missive = missive_for_campaign_preview(campaign, "email")

    ctx = build_preview_context(missive)

    assert ctx["to_recipients"] == []
    assert ctx["cc_recipients"] == []
    assert "notification_recipients" not in ctx


def test_postal_context_exposes_letter_chrome():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
        sender_name="Octolo",
        sender_address={
            "address_line1": "1 rue de la Paix",
            "postal_code": "75002",
            "city": "Paris",
        },
    )
    recipient = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        address={"address_line1": "10 rue Example", "city": "Lyon"},
        recipient_type=MissiveRecipientType.RECIPIENT,
    )

    ctx = build_preview_context(missive, postal_recipient_pk=recipient.pk)

    assert "1 rue de la Paix" in _address_text(ctx["sender_address"])
    assert "Paris" in _address_text(ctx["sender_address"])
    assert ctx["postal_letter_recipient"]["pk"] == recipient.pk
    assert "10 rue Example" in _address_text(ctx["postal_letter_recipient"]["address"])
    assert "Lyon" in _address_text(ctx["postal_letter_recipient"]["address"])


def _address_text(address) -> str:
    return " ".join(" ".join(line) for line in address.text_3lines)


def _sms(**kwargs) -> Missive:
    values = {
        "missive_type": MissiveType.SMS,
        "status": MissiveStatus.DRAFT,
        "body_text": "Hello",
        "sender_name": "Octolo",
        "sender_phone": "+33987654321",
    }
    values.update(kwargs)
    return Missive.objects.create(**values)


def test_sms_context_uses_runtime_recipients_and_ignores_other_roles():
    missive = _sms()
    MissiveRecipient.objects.create(
        missive=missive,
        name="Persisted",
        phone="+33000000000",
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    missive._preview_runtime = PreviewRuntimeData(
        recipients=(
            PreviewRecipient(
                recipient_type=MissiveRecipientType.RECIPIENT,
                name="Ada Lovelace",
                phone="+33111111111",
            ),
            PreviewRecipient(
                recipient_type=MissiveRecipientType.CC,
                name="Skipped",
                phone="+33222222222",
            ),
        )
    )

    context = build_preview_context(missive)

    assert context["sender"]["name"] == "Octolo"
    assert context["sender"]["phone"] == "+33987654321"
    assert context["to_recipients"] == [{"pk": None, "name": "Ada Lovelace", "phone": "+33111111111"}]
    rendered = render_to_string("django_pymissive/sms_preview.html", {**context, "missive": missive})
    assert "Ada Lovelace" not in rendered
    assert "+33111111111" not in rendered
    assert "Skipped" not in rendered
    assert "Persisted" not in rendered
    assert "Octolo" in rendered


def test_sms_context_lists_persisted_recipients():
    missive = _sms()
    kept = MissiveRecipient.objects.create(
        missive=missive,
        name="Ada",
        phone="+33111111111",
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Copied",
        phone="+33222222222",
        recipient_type=MissiveRecipientType.BCC,
    )

    context = build_preview_context(missive)

    assert context["sender"]["name"] == "Octolo"
    assert context["to_recipients"] == [{"pk": kept.pk, "name": "Ada", "phone": "+33111111111"}]


def test_sms_context_fills_missing_sender_from_post():
    missive = SimpleNamespace(
        missive_type="sms",
        sender={"name": "", "phone": ""},
        _preview_runtime=PreviewRuntimeData(),
        is_persisted=False,
    )

    context = build_preview_context(
        missive,
        post_data={"sender_phone": "+33999999999", "sender_phone_name": "Desk"},
    )

    assert context["sender"]["phone"] == "+33999999999"
    assert context["sender"]["name"] == "Desk"
    assert context["to_recipients"] == []


def test_sms_context_has_no_recipients_without_runtime_rows():
    missive = _sms()
    missive._preview_runtime = PreviewRuntimeData()

    assert build_preview_context(missive)["to_recipients"] == []


def test_postal_preview_normalizes_every_supported_address_form():
    native = SimpleNamespace(text_3lines=(("1 native street",),))
    missive = Missive(
        missive_type=MissiveType.LETTER,
        status=MissiveStatus.DRAFT,
        body_text="Letter",
        sender_name="Octolo",
        sender_address={"address_line1": "1 rue Expediteur", "city": "Paris"},
    )
    missive._preview_runtime = PreviewRuntimeData(
        recipients=(
            PreviewRecipient(
                recipient_type=MissiveRecipientType.RECIPIENT,
                name="Native",
                address=native,
                pk=11,
            ),
            PreviewRecipient(
                recipient_type=MissiveRecipientType.RECIPIENT,
                name="Structured",
                address={
                    "address_line1": "2 rue Structure",
                    "postal_code": "69000",
                    "city": "Lyon",
                },
                pk=12,
            ),
            PreviewRecipient(
                recipient_type=MissiveRecipientType.RECIPIENT,
                name="Legacy",
                address="12 rue Legacy",
                pk=13,
            ),
            PreviewRecipient(
                recipient_type=MissiveRecipientType.RECIPIENT,
                name="Empty",
                address="   ",
                pk=14,
            ),
            PreviewRecipient(
                recipient_type=MissiveRecipientType.CC,
                name="Copied",
                address="hidden",
                pk=15,
            ),
        )
    )

    selected = build_preview_context(missive, postal_recipient_pk=13)
    recipients = {row["name"]: row for row in selected["postal_recipients"]}

    assert recipients["Native"]["address"] is native
    assert "2 rue Structure" in _address_text(recipients["Structured"]["address"])
    assert "Lyon" in _address_text(recipients["Structured"]["address"])
    assert recipients["Structured"]["address"]["city"] == "Lyon"
    assert isinstance(recipients["Structured"]["address"], dict)
    assert json.loads(json.dumps(recipients["Structured"]["address"]))["city"] == "Lyon"
    assert recipients["Legacy"]["address"].text_3lines == (("12 rue Legacy",),)
    assert recipients["Legacy"]["address"] == "12 rue Legacy"
    assert isinstance(recipients["Legacy"]["address"], str)
    assert str(recipients["Legacy"]["address"]) == "12 rue Legacy"
    assert json.loads(json.dumps(recipients["Legacy"]["address"])) == "12 rue Legacy"
    assert recipients["Empty"]["address"] is None
    assert "Copied" not in recipients
    assert selected["postal_letter_recipient"]["pk"] == 13
    assert selected["postal_letter_recipient_pk"] == 13
    assert "1 rue Expediteur" in _address_text(selected["sender_address"])
    assert "Paris" in _address_text(selected["sender_address"])
    assert selected["sender_address"]["city"] == "Paris"
    rendered = render_to_string(
        "django_pymissive/postal_preview.html",
        {**selected, "missive": missive, "provider_address_css": ""},
    )
    assert "12 rue Legacy" in rendered
    assert "Copied" not in rendered


def test_postal_context_reads_persisted_recipients_in_name_order():
    missive = Missive.objects.create(
        missive_type=MissiveType.LETTER,
        status=MissiveStatus.DRAFT,
        sender_name="Octolo",
        sender_address={"address_line1": "1 rue de la Paix", "city": "Paris"},
    )
    second = MissiveRecipient.objects.create(
        missive=missive,
        name="Zoe",
        address={"address_line1": "9 rue Zoe", "city": "Nice"},
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    first = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        address={"address_line1": "2 rue Alice", "city": "Lille"},
        recipient_type=MissiveRecipientType.RECIPIENT,
    )

    context = build_preview_context(missive, postal_recipient_pk=second.pk)

    assert [row["pk"] for row in context["postal_recipients"]] == [first.pk, second.pk]
    assert context["postal_letter_recipient"]["pk"] == second.pk
    assert "9 rue Zoe" in _address_text(context["postal_letter_recipient"]["address"])


def test_unknown_type_returns_empty_context():
    missive = Missive(missive_type="notification", status=MissiveStatus.DRAFT)

    assert build_preview_context(missive) == {}


def test_a_failing_builder_is_not_swallowed():
    missive = _email_missive()

    with (
        patch(
            "django_pymissive.services.preview._build_email_context",
            side_effect=RuntimeError("broken header"),
        ),
        pytest.raises(RuntimeError, match="broken header"),
    ):
        build_preview_context(missive)


def test_resolver_keeps_standalone_missive_context_local():
    missive = _email_missive(additional_context={"origin": "missive"})

    preview = resolve_preview(missive)

    assert preview.missive is missive
    assert preview.campaign is None
    assert preview.campaign_step is None
    assert preview.missive.missive_context()["origin"] == "missive"


def test_resolver_merges_campaign_step_and_missive_context():
    campaign = MissiveCampaign.objects.create(
        subject="Campaign",
        additional_context={"shared": "campaign", "campaign_only": True},
    )
    step = CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=MissiveType.EMAIL,
        subject="Step",
        body_text="{{ shared }}",
        additional_context={"shared": "step", "step_only": True},
    )
    missive = _email_missive(
        campaign_step=step,
        additional_context={"shared": "missive", "missive_only": True},
    )

    preview = resolve_preview(missive)

    assert preview.campaign == campaign
    assert preview.campaign_step == step
    context = preview.missive.missive_context()
    assert context["shared"] == "missive"
    assert context["campaign_only"] is True
    assert context["step_only"] is True
    assert context["missive_only"] is True


def test_step_resolver_builds_unsaved_missive_and_common_render_context():
    campaign = MissiveCampaign.objects.create(
        subject="Campaign",
        additional_context={"campaign_token": "campaign"},
    )
    step = CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=MissiveType.EMAIL,
        subject="Step",
        body_text="{{ campaign_token }}-{{ step_token }}",
        additional_context={"step_token": "step"},
    )

    preview = resolve_preview(step)
    context = build_render_context(preview)

    assert preview.missive._state.adding
    assert preview.campaign == campaign
    assert preview.campaign_step == step
    assert "campaign-step" in preview.missive.body_text_compiled
    assert context["missive"] is preview.missive
    assert context["campaign"] == campaign
    assert context["campaign_step"] == step


def test_get_post_and_pdf_entrypoints_share_the_resolver():
    campaign = MissiveCampaign.objects.create(subject="Campaign")
    step = CampaignStep.objects.create(
        campaign=campaign,
        position=1,
        missive_type=MissiveType.EMAIL,
        subject="Step",
        body_text="Body",
    )
    user = get_user_model().objects.create_user(username="preview-entrypoints", is_staff=True)
    client = Client()
    client.force_login(user)
    preview_url = reverse("django_pymissive:preview", args=["campaign", campaign.pk])
    form_url = reverse("django_pymissive:preview_form", args=["campaign"])
    pdf_url = reverse("django_pymissive:download_pdf", args=["campaign", campaign.pk])
    query = {"type": "email", "step": step.pk}

    with patch("django_pymissive.views.preview.preview_service.resolve_preview", wraps=resolve_preview) as resolver:
        assert client.get(preview_url, query).status_code == 200
        assert client.post(f"{form_url}?type=email&step={step.pk}&pk={campaign.pk}", {}).status_code == 200
        with patch.object(Missive, "body_to_pdf", return_value=b"%PDF"):
            assert client.get(pdf_url, query).status_code == 200

    assert resolver.call_count == 3


def test_letter_and_registered_letter_share_the_postal_preview_layout():
    letter = Missive.objects.create(
        missive_type=MissiveType.LETTER,
        status=MissiveStatus.DRAFT,
        body_rich="<p>simple</p>",
        sender_name="Octolo",
        sender_address={"address_line1": "1 rue de la Paix", "city": "Paris"},
    )
    registered_letter = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
        body_rich="<p>registered</p>",
        sender_name="Octolo",
        sender_address={"address_line1": "1 rue de la Paix", "city": "Paris"},
    )
    assert letter.missive_type != registered_letter.missive_type
    assert letter.missive_type in POSTAL_PREVIEW_MISSIVE_TYPES
    assert registered_letter.missive_type in POSTAL_PREVIEW_MISSIVE_TYPES
    assert letter.is_postal_like()
    assert registered_letter.is_postal_like()
    assert letter.check_letter() is False  # no recipient yet
    MissiveRecipient.objects.create(
        missive=letter,
        name="Alice",
        address={"address_line1": "10 rue Example", "city": "Lyon"},
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    letter.refresh_from_db()
    assert letter.check_letter()
    assert letter.check_registered_letter()  # same body check

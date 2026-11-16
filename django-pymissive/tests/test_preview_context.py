"""``build_preview_context`` must not swallow a broken preview into ``{}``."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.campaign_step import CampaignStep
from django_pymissive.models.choices import MissiveRecipientType, MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from django_pymissive.services.preview import build_render_context, resolve_preview
from django_pymissive.views.preview import (
    POSTAL_PREVIEW_MISSIVE_TYPES,
    build_preview_context,
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

    assert ctx["sender_address"]["city"] == "Paris"
    assert ctx["postal_letter_recipient"]["pk"] == recipient.pk


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

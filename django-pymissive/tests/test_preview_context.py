"""``build_preview_context`` must not swallow a broken preview into ``{}``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models.campaign import MissiveCampaign
from django_pymissive.models.choices import MissiveRecipientType, MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from django_pymissive.views.preview import (
    build_preview_context,
    missive_for_campaign_preview,
)

pytestmark = pytest.mark.django_db


def _email_missive(**kw) -> Missive:
    defaults = dict(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        body_text="Body",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )
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


def test_unsaved_campaign_missive_skips_recipients_without_raising():
    campaign = MissiveCampaign.objects.create(subject="Campaign")
    missive = missive_for_campaign_preview(campaign, "email")

    ctx = build_preview_context(missive)

    assert ctx["to_recipients"] == []
    assert ctx["cc_recipients"] == []


def test_postal_context_exposes_letter_chrome():
    missive = Missive.objects.create(
        missive_type=MissiveType.LRE,
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
    assert ctx["acknowledgement_display"]
    assert ctx["priority_display"]


def test_unknown_type_returns_empty_context():
    missive = Missive(missive_type="notification", status=MissiveStatus.DRAFT)

    assert build_preview_context(missive) == {}


def test_a_failing_builder_is_not_swallowed():
    missive = _email_missive()

    with patch(
        "django_pymissive.views.preview._build_email_context",
        side_effect=RuntimeError("broken header"),
    ):
        with pytest.raises(RuntimeError, match="broken header"):
            build_preview_context(missive)

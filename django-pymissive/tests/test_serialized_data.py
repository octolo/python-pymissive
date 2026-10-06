"""Tests for lightweight ``get_serialized_data(attachments=False)`` serialization."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from django_pymissive.models.choices import MissiveRecipientType
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from tests.processors import SIGNATURE_TEXT

pytestmark = pytest.mark.django_db

SIGNATURE_CHAIN = [
    "django_pymissive.processors.body.django_template.django_template_processor",
    "tests.processors.add_signature",
]


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_get_serialized_data_without_attachments_skips_body_processors():
    missive = Missive.objects.create(
        missive_type="email",
        body_text="hello",
        external_id="ext-123",
    )
    with patch.object(missive, "get_webhook_url", return_value="https://example.com/hook"):
        with patch.object(
            missive,
            "apply_body_processors",
            side_effect=AssertionError("body processors must not run"),
        ):
            data = missive.get_serialized_data(attachments=False)

    assert data["body_text"] == "hello"
    assert "attachments" not in data
    assert data["external_id"] == "ext-123"


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_get_serialized_data_attachments_false_compiled_true_still_compiles():
    missive = Missive.objects.create(missive_type="email", body_text="hello")
    with patch.object(missive, "get_webhook_url", return_value="https://example.com/hook"):
        data = missive.get_serialized_data(attachments=False, compiled=True)
    assert data["body_text"].endswith(SIGNATURE_TEXT)
    assert "attachments" not in data


@override_settings(PYMISSIVE_DEFAULT_BODY_PROCESSORS=SIGNATURE_CHAIN)
def test_get_serialized_data_without_attachments_skips_first_document_generation():
    missive = Missive.objects.create(
        missive_type="registered_letter",
        body_rich="<p>letter</p>",
        external_id="ext-registered_letter",
    )
    with patch.object(missive, "get_webhook_url", return_value="https://example.com/hook"):
        with patch.object(
            missive,
            "generate_first_document",
            side_effect=AssertionError("first_document must not be generated"),
        ):
            data = missive.get_serialized_data(attachments=False)

    assert "attachments" not in data
    assert data["body_rich"] == "<p>letter</p>"


def test_get_serialized_data_includes_notification_recipients():
    missive = Missive.objects.create(missive_type="letter", subject="Letter")
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
    MissiveRecipient.objects.create(
        missive=missive,
        name="Backup",
        email="backup@example.com",
        recipient_type=MissiveRecipientType.NOTIFICATION,
    )

    with patch.object(missive, "get_webhook_url", return_value="https://example.com/hook"):
        data = missive.get_serialized_data(attachments=False)

    assert [r["email"] for r in data["recipients"]] == ["alice@example.com"]
    assert [r["email"] for r in data["notification"]] == [
        "ops@example.com",
        "backup@example.com",
    ]
    assert "cc" not in data
    assert "bcc" not in data


def test_duplicate_missive_copies_tags():
    source = Missive.objects.create(
        missive_type="email",
        subject="Hello",
        tags=["welcome", "invoice"],
    )
    clone = source.duplicate_missive()
    clone.refresh_from_db()
    assert clone.pk != source.pk
    assert clone.tags == ["welcome", "invoice"]


def test_duplicate_action_saves_posted_tags_first():
    from django.contrib import admin as django_admin
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    source = Missive.objects.create(
        missive_type="email",
        subject="Hello",
        tags=[],
    )
    request = RequestFactory().post("/", {"tags": '["welcome", "invoice"]'})
    request.session = {}
    request._messages = FallbackStorage(request)
    missive_admin = django_admin.site._registry[Missive]
    missive_admin.handle_duplicate_missive(request, source.pk)

    source.refresh_from_db()
    clone = Missive.objects.exclude(pk=source.pk).get()
    assert source.tags == ["welcome", "invoice"]
    assert clone.tags == ["welcome", "invoice"]


def test_serialized_tags_are_kept_for_the_provider():
    missive = Missive.objects.create(
        missive_type="email",
        subject="Hello",
        tags=["welcome", "invoice"],
        additional_config={"tags": ["config"]},
    )
    with patch.object(missive, "get_webhook_url", return_value=None):
        data = missive.get_serialized_data(attachments=False)
    assert data["tags"] == ["welcome", "invoice"]

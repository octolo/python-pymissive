"""Tests for lightweight ``get_serialized_data(attachments=False)`` serialization."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from django_pymissive.models.missive import Missive
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
        missive_type="lre",
        body_rich="<p>letter</p>",
        external_id="ext-lre",
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

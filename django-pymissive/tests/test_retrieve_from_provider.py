"""Retrieve a missive from provider partner ID or internal UID."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from django_pymissive.forms.missive import RetrieveMissiveForm
from django_pymissive.models import MissiveRecipient
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.retrieve import get_or_retrieve_from_provider, lookup_missive

pytestmark = pytest.mark.django_db


def _email_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "body_text": "Body",
        "sender_name": "Octolo",
        "sender_email": "hello@example.com",
        "status": MissiveStatus.DRAFT,
        "provider": "brevo",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_form_requires_partner_id_or_uid():
    form = RetrieveMissiveForm(
        data={"provider": "brevo", "missive_type": MissiveType.EMAIL}
    )
    assert form.is_valid() is False


def test_form_accepts_partner_id():
    form = RetrieveMissiveForm(
        data={
            "provider": "brevo",
            "missive_type": MissiveType.EMAIL,
            "partner_id": "msg-123",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["partner_id"] == "msg-123"


def test_lookup_by_external_id():
    missive = _email_missive(external_id="ext-abc")
    found = lookup_missive(partner_id="ext-abc")
    assert found == missive


def test_lookup_partner_id_falls_back_to_uid():
    missive = _email_missive()
    found = lookup_missive(partner_id=str(missive.pk))
    assert found == missive


def test_lookup_by_uid():
    missive = _email_missive()
    found = lookup_missive(uid=missive.pk)
    assert found == missive


def test_lookup_unknown_partner_id_returns_none():
    assert lookup_missive(partner_id="not-a-uuid") is None


def test_get_or_retrieve_returns_existing_without_provider_call():
    missive = _email_missive(external_id="ext-existing")
    with patch.object(Missive, "call_provider_service") as retrieve:
        found, created = get_or_retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-existing",
        )
    retrieve.assert_not_called()
    assert created is False
    assert found.pk == missive.pk


def test_get_or_retrieve_creates_from_provider():
    response = {
        "external_id": "ext-new",
        "message_id": "ext-new",
        "subject": "Retrieved subject",
        "body_text": "Retrieved body",
        "sender_email": "from@example.com",
        "recipients": [{"email": "alice@example.com", "name": "Alice"}],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = get_or_retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-new",
        )
    assert created is True
    missive.refresh_from_db()
    assert missive.external_id == "ext-new"
    assert missive.subject == "Retrieved subject"
    assert missive.body_text == "Retrieved body"
    assert missive.sender_email == "from@example.com"
    assert MissiveRecipient.objects.filter(
        missive=missive, email="alice@example.com"
    ).exists()


def test_get_or_retrieve_creates_recipients_from_events():
    response = {
        "message_id": "ext-evt",
        "events": [
            {"email": "one@example.com", "event": "delivered"},
            {"email": "one@example.com", "event": "opened"},
            {"recipient": {"email": "two@example.com"}, "event": "sent"},
        ],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = get_or_retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-evt",
        )
    assert created is True
    emails = set(
        MissiveRecipient.objects.filter(missive=missive).values_list("email", flat=True)
    )
    assert emails == {"one@example.com", "two@example.com"}


def test_get_or_retrieve_uses_uid_as_pk():
    uid = uuid4()
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "from-uid",
            "subject": "From uid",
            "events": [],
        },
    ), patch.object(Missive, "handle_events"):
        missive, created = get_or_retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            uid=uid,
        )
    assert created is True
    assert missive.pk == uid
    assert missive.external_id == "from-uid"


def test_get_or_retrieve_does_not_create_when_not_found():
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={"message_id": "missing", "events": []},
    ):
        with pytest.raises(ValidationError, match="not found"):
            get_or_retrieve_from_provider(
                provider="brevo",
                missive_type=MissiveType.EMAIL,
                partner_id="missing",
            )
    assert Missive.objects.filter(external_id="missing").exists() is False


def test_get_or_retrieve_rejects_provider_without_retrieve():
    with patch.object(Missive, "has_service", return_value=False):
        with pytest.raises(ValidationError):
            get_or_retrieve_from_provider(
                provider="brevo",
                missive_type=MissiveType.EMAIL,
                partner_id="missing",
            )
    assert Missive.objects.filter(external_id="missing").exists() is False


def test_admin_retrieve_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missive_retrieve_from_provider")
    response = client.get(url)
    assert response.status_code == 200
    assert b"partner_id" in response.content or b"Partner" in response.content


def test_admin_retrieve_post_redirects_to_existing():
    missive = _email_missive(external_id="ext-admin")
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missive_retrieve_from_provider")
    response = client.post(
        url,
        {
            "provider": "brevo",
            "missive_type": MissiveType.EMAIL,
            "partner_id": "ext-admin",
        },
    )
    assert response.status_code == 302
    assert str(missive.pk) in response["Location"]

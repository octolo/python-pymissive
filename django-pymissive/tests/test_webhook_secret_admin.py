"""Admin boost view that generates a webhook secret from SECRET_KEY."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_pymissive.forms.webhook import GenerateWebhookSecretForm
from pymissive.webhook_secret import generate_webhook_secret

pytestmark = pytest.mark.django_db


def _url():
    return reverse("admin:django_pymissive_missivewebhook_generate_webhook_secret")


def _admin_client():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    return client


def test_form_requires_provider():
    assert GenerateWebhookSecretForm(data={}).is_valid() is False


def test_form_accepts_a_provider():
    form = GenerateWebhookSecretForm(data={"provider": "brevo"})
    assert form.is_valid() is True
    assert str(form.cleaned_data["provider"]) == "brevo"


def test_admin_get_renders_the_form():
    response = _admin_client().get(_url())
    assert response.status_code == 200
    assert b"provider" in response.content.lower()


def test_admin_post_shows_the_secret_seeded_by_django_secret():
    response = _admin_client().post(_url(), {"provider": "brevo"})
    assert response.status_code == 200
    expected = generate_webhook_secret(
        "brevo",
        settings.SECRET_KEY,
        when=datetime.now(timezone.utc).date(),
    )
    assert expected.encode() in response.content


def test_anonymous_user_is_rejected():
    response = Client().get(_url())
    assert response.status_code in (302, 403)

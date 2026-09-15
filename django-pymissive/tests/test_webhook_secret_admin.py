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
    assert GenerateWebhookSecretForm(data={"missive_type": "email"}).is_valid() is False


def test_form_requires_missive_type():
    assert GenerateWebhookSecretForm(data={"provider": "brevo"}).is_valid() is False


def test_form_accepts_a_provider():
    form = GenerateWebhookSecretForm(data={"provider": "brevo", "missive_type": "email"})
    assert form.is_valid() is True
    assert str(form.cleaned_data["provider"]) == "brevo"
    assert str(form.cleaned_data["missive_type"]) == "email"
    assert form.cleaned_data.get("salt") in ("", None)


def test_form_accepts_an_optional_salt():
    form = GenerateWebhookSecretForm(
        data={"provider": "brevo", "missive_type": "email", "salt": "rotate-1"}
    )
    assert form.is_valid() is True
    assert form.cleaned_data["salt"] == "rotate-1"


def test_admin_get_renders_the_form():
    response = _admin_client().get(_url())
    assert response.status_code == 200
    html = response.content.decode().lower()
    assert "provider" in html
    assert "missive_type" in html
    assert "salt" in html
    assert response.context["readonly_fields"] == [
        "secret",
        "webhook_url",
        "webhook_url_token",
    ]


def test_admin_post_shows_the_secret_and_both_webhook_urls():
    response = _admin_client().post(
        _url(), {"provider": "brevo", "missive_type": "email"}
    )
    assert response.status_code == 200
    expected = generate_webhook_secret(
        "brevo",
        settings.SECRET_KEY,
        when=datetime.now(timezone.utc).date(),
    )
    html = response.content.decode()
    assert expected in html
    assert "/missive/webhook/brevo/email/" in html
    assert f"/missive/webhook/brevo/email/{expected}/" in html
    assert response.context["readonly_fields"] == [
        "secret",
        "webhook_url",
        "webhook_url_token",
    ]


def test_admin_post_scaleway_url_includes_the_token():
    response = _admin_client().post(
        _url(), {"provider": "scaleway", "missive_type": "email"}
    )
    assert response.status_code == 200
    token = generate_webhook_secret(
        "scaleway",
        settings.SECRET_KEY,
        when=datetime.now(timezone.utc).date(),
    )
    html = response.content.decode()
    assert token in html
    assert "/missive/webhook/scaleway/email/" in html
    assert f"/missive/webhook/scaleway/email/{token}/" in html


def test_admin_post_salt_mints_a_different_token():
    salted = _admin_client().post(
        _url(),
        {"provider": "brevo", "missive_type": "email", "salt": "rotate-1"},
    )
    assert salted.status_code == 200
    expected = generate_webhook_secret(
        "brevo",
        f"{settings.SECRET_KEY}\nrotate-1",
        when=datetime.now(timezone.utc).date(),
    )
    unsalted = generate_webhook_secret(
        "brevo",
        settings.SECRET_KEY,
        when=datetime.now(timezone.utc).date(),
    )
    html = salted.content.decode()
    assert expected in html
    assert expected != unsalted
    assert unsalted not in html
    assert "rotate-1" in html


def test_anonymous_user_is_rejected():
    response = Client().get(_url())
    assert response.status_code in (302, 403)

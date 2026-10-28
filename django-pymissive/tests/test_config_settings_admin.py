"""The configuration admin lists every setting the package reads."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_pymissive.models.setting import MissiveSetting

pytestmark = pytest.mark.django_db


def _url():
    return reverse("admin:django_pymissive_missiveconfig_show_settings")


def _admin_client():
    get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="x")
    client = Client()
    client.force_login(get_user_model().objects.get(username="admin"))
    return client


def test_changelist_links_to_the_settings_view():
    response = _admin_client().get(reverse("admin:django_pymissive_missiveconfig_changelist"))
    assert response.status_code == 200
    assert _url() in response.content.decode()


def test_settings_view_lists_configured_and_default_values(settings):
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    settings.PYMISSIVE_CUSTOM_FLAG = "hello"

    rows = {row.name: row for row in MissiveSetting.objects.all()}
    assert rows["PYMISSIVE_DEFAULT_PROVIDER"].default_value == "—"
    assert rows["PYMISSIVE_DEFAULT_PROVIDER"].configured_value == "fake"
    assert "PYMISSIVE_CUSTOM_FLAG" not in rows
    assert all(name.startswith("PYMISSIVE_") for name in rows)
    assert rows["PYMISSIVE_SEND_CHUNK_SIZE"].default_value == "500"
    assert rows["PYMISSIVE_SEND_CHUNK_SIZE"].configured_value == ""
    assert rows["PYMISSIVE_DRY_RUN"].default_value == "false"
    assert rows["PYMISSIVE_DRY_RUN"].configured_value == "false"
    assert "PYMISSIVE_DEFAULT_BODY_PROCESSORS" in rows
    assert "PYMISSIVE_AUTHENTICATED_ACKNOWLEDGEMENT" in rows

    response = _admin_client().get(_url())
    assert response.status_code == 200
    body = response.content.decode()
    assert "<strong>PYMISSIVE_DEFAULT_PROVIDER</strong>" in body
    assert "color: var(--secondary)" in body
    assert "color: #fff" in body
    assert "fake" in body
    assert "PYMISSIVE_SEND_CHUNK_SIZE" in body
    assert "PYMISSIVE_CUSTOM_FLAG" not in body


def test_settings_view_formats_nested_callable_values(settings):
    from django_pymissive.processors.allowed import staff_emails

    settings.PYMISSIVE_RECIPIENT_ALLOWED = {
        "email": [staff_emails],
    }

    row = MissiveSetting.objects.get(name="PYMISSIVE_RECIPIENT_ALLOWED")
    assert row.configured_value == '{"email": ["django_pymissive.processors.allowed.staff_emails"]}'
    response = _admin_client().get(_url())
    assert response.status_code == 200
    assert "django_pymissive.processors.allowed.staff_emails" in response.content.decode()

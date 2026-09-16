"""Locked missives render GeoaddressField with django-geoaddress native readonly."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_pymissive.models import MissiveRecipientAddress
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _postal_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.REGISTERED_LETTER,
        "subject": "LRAR",
        "status": MissiveStatus.DRAFT,
        "sender_name": "Octolo",
        "sender_address": {
            "address_line1": "1 rue de la Paix",
            "postal_code": "75002",
            "city": "Paris",
            "country": "France",
        },
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def _admin_client():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    return client


def test_locked_missive_recipient_address_uses_geoaddress_readonly_widget():
    missive = _postal_missive(external_id="mv-sending-1")
    MissiveRecipientAddress.objects.create(
        missive=missive,
        name="Alice Martin",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country": "France",
        },
    )
    client = _admin_client()
    url = reverse("admin:django_pymissive_missive_change", args=[missive.pk])
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "geoaddress-autocomplete-readonly" in html
    assert "10 rue Example" in html
    assert "75001" in html
    assert "Paris" in html
    assert 'name="_save"' not in html


def test_tracking_number_is_clickable_on_recipient_admin():
    missive = _postal_missive()
    rec = MissiveRecipientAddress.objects.create(
        missive=missive,
        name="Alice Martin",
        tracking_number="2C123456789FR",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country_code": "FR",
        },
    )
    client = _admin_client()
    url = reverse("admin:django_pymissive_missiverecipient_change", args=[rec.pk])
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert (
        'href="https://www.laposte.fr/outils/suivre-vos-envois?code=2C123456789FR"'
        in html
    )
    assert "2C123456789FR" in html
    assert 'target="_blank"' in html


def test_tracking_number_is_clickable_on_missive_address_inline():
    missive = _postal_missive()
    MissiveRecipientAddress.objects.create(
        missive=missive,
        name="Alice Martin",
        tracking_number="2C123456789FR",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country_code": "FR",
        },
    )
    client = _admin_client()
    url = reverse("admin:django_pymissive_missive_change", args=[missive.pk])
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert (
        'href="https://www.laposte.fr/outils/suivre-vos-envois?code=2C123456789FR"'
        in html
    )
    assert "2C123456789FR" in html


def test_draft_missive_recipient_address_stays_editable():
    missive = _postal_missive()
    MissiveRecipientAddress.objects.create(
        missive=missive,
        name="Alice Martin",
        address={
            "address_line1": "10 rue Example",
            "city": "Paris",
        },
    )
    client = _admin_client()
    url = reverse("admin:django_pymissive_missive_change", args=[missive.pk])
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert "geoaddress-autocomplete-readonly" not in html
    assert 'name="_save"' in html

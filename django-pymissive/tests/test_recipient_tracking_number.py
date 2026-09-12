"""Carrier tracking_number on recipients is distinct from provider external_id."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models import MissiveRecipientEmail
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.retrieve import retrieve_from_provider

pytestmark = pytest.mark.django_db


def _email_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "body_text": "Body",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_serialized_recipient_includes_tracking_number():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        tracking_number="2C123456789FR",
    )
    assert rec.get_serialized_data()["tracking_number"] == "2C123456789FR"
    assert rec.get_serialized_data()["external_id"] is None


def test_update_recipients_persists_tracking_number():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive, name="Alice", email="alice@example.com"
    )
    missive._update_recipients(
        [
            {
                "internal_id": str(rec.id),
                "external_id": "mv-recipient-1",
                "tracking_number": "2C123456789FR",
            }
        ]
    )
    rec.refresh_from_db()
    assert rec.external_id == "mv-recipient-1"
    assert rec.tracking_number == "2C123456789FR"


def test_update_recipients_does_not_wipe_tracking_number_when_absent():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        tracking_number="2CKEEP",
    )
    missive._update_recipients(
        [{"internal_id": str(rec.id), "external_id": "mv-2"}]
    )
    rec.refresh_from_db()
    assert rec.tracking_number == "2CKEEP"


def test_duplicate_recipients_clears_tracking_number():
    source = _email_missive()
    MissiveRecipientEmail.objects.create(
        missive=source,
        name="Alice",
        email="alice@example.com",
        external_id="mv-1",
        tracking_number="2C123456789FR",
    )
    clone = _email_missive(subject="Clone")
    source.duplicate_recipients(clone, source)
    cloned = clone.to_missiverecipient.get()
    assert cloned.external_id is None
    assert cloned.tracking_number is None


def test_retrieve_missive_updates_tracking_number():
    missive = _email_missive(external_id="ext-1")
    rec = MissiveRecipientEmail.objects.create(
        missive=missive, name="Alice", email="alice@example.com"
    )
    with patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "recipients": [
                {
                    "internal_id": str(rec.id),
                    "external_id": "mv-1",
                    "tracking_number": "2CABC",
                }
            ],
            "events": [],
        },
    ):
        missive.retrieve_missive()
    rec.refresh_from_db()
    assert rec.tracking_number == "2CABC"


def test_get_or_retrieve_creates_recipient_with_tracking_number():
    response = {
        "external_id": "ext-track",
        "subject": "Retrieved",
        "recipients": [
            {
                "email": "alice@example.com",
                "name": "Alice",
                "tracking_number": "2C123456789FR",
            }
        ],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-track",
        )
    assert created is True
    rec = missive.to_missiverecipient.get()
    assert rec.tracking_number == "2C123456789FR"


def test_can_tracking_numbers_requires_service_and_external_id():
    missive = _email_missive()
    with patch.object(Missive, "has_service", return_value=True):
        assert missive.can_tracking_numbers() is False
    missive.external_id = "ext-1"
    missive.save(update_fields=["external_id"])
    with patch.object(Missive, "has_service", return_value=False):
        assert missive.can_tracking_numbers() is False
    with patch.object(Missive, "has_service", return_value=True):
        assert missive.can_tracking_numbers() is True


def test_retrieve_tracking_numbers_persists_provider_response():
    missive = _email_missive(external_id="ext-1")
    rec = MissiveRecipientEmail.objects.create(
        missive=missive, name="Alice", email="alice@example.com"
    )
    with patch.object(Missive, "can_tracking_numbers", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value=[
            {
                "internal_id": str(rec.id),
                "external_id": "mv-1",
                "tracking_number": "2CABC",
            }
        ],
    ) as call_provider:
        result = missive.retrieve_tracking_numbers()
    call_provider.assert_called_once()
    assert call_provider.call_args.args[0] == "tracking_number"
    rec.refresh_from_db()
    assert rec.tracking_number == "2CABC"
    assert result[0]["tracking_number"] == "2CABC"


def test_retrieve_tracking_numbers_skips_when_unsupported():
    missive = _email_missive(external_id="ext-1")
    with patch.object(Missive, "can_tracking_numbers", return_value=False), patch.object(
        Missive, "call_provider_service"
    ) as call_provider:
        assert missive.retrieve_tracking_numbers() == []
    call_provider.assert_not_called()


def _postal_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.LRE,
        "subject": "LRAR",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_tracking_url_substitutes_number_from_geoaddress_country():
    from django_pymissive.models import MissiveRecipient

    missive = _postal_missive()
    rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        tracking_number="2C123456789FR",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country_code": "FR",
        },
    )
    assert rec.tracking_url == (
        "https://www.laposte.fr/outils/suivre-vos-envois?code=2C123456789FR"
    )


def test_tracking_url_uses_italy_when_country_code_is_it():
    from django_pymissive.models import MissiveRecipient

    missive = _postal_missive()
    rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Marco",
        tracking_number="RW799210633FR",
        address={"city": "Roma", "country_code": "it"},
    )
    assert rec.tracking_url == (
        "https://www.poste.it/cerca/index.html#/risultati-spedizioni/RW799210633FR"
    )


def test_tracking_url_is_none_without_tracking_number():
    from django_pymissive.models import MissiveRecipient

    missive = _postal_missive()
    rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        address={"country_code": "FR"},
    )
    assert rec.tracking_url is None


def test_tracking_url_is_none_without_address():
    from django_pymissive.models import MissiveRecipient

    missive = _postal_missive()
    rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        tracking_number="2CABC",
    )
    assert rec.tracking_url is None


def test_tracking_url_is_none_for_unknown_country():
    from django_pymissive.models import MissiveRecipient

    missive = _postal_missive()
    rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        tracking_number="ABC123",
        address={"country_code": "XX"},
    )
    assert rec.tracking_url is None


def test_get_tracking_url_replaces_placeholder_when_number_present():
    from pymissive.postal_tracking import get_tracking_url

    assert get_tracking_url("FR", "2CABC") == (
        "https://www.laposte.fr/outils/suivre-vos-envois?code=2CABC"
    )
    assert get_tracking_url("FR") is None
    assert get_tracking_url("BG") == "https://www.bgpost.bg/en/500"
    assert get_tracking_url(None, "2CABC") is None

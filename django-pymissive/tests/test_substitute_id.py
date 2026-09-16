"""substitute_id stores provider custom_id / imported internal refs."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from django_pymissive.forms.missive import RetrieveMissiveForm
from django_pymissive.models import MissiveRecipientEmail
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.retrieve import lookup_missive, retrieve_from_provider
from pymissive.providers.maileva import _provider_custom_id

pytestmark = pytest.mark.django_db


def _email_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "body_text": "Body",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_missive_save_leaves_substitute_id_null():
    missive = _email_missive()
    assert missive.substitute_id is None


def test_recipient_save_leaves_substitute_id_null():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive, name="Alice", email="alice@example.com"
    )
    assert rec.substitute_id is None


def test_serialized_recipient_sends_null_substitute_id_when_unset():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive, name="Alice", email="alice@example.com"
    )
    data = rec.get_serialized_data()
    assert data["substitute_id"] is None
    assert data["id"] == str(rec.id)


def test_serialized_recipient_includes_substitute_id():
    missive = _email_missive()
    rec = MissiveRecipientEmail.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        substitute_id="legacy-rec",
    )
    assert rec.get_serialized_data()["substitute_id"] == "legacy-rec"
    assert rec.get_serialized_data()["id"] == str(rec.id)


def test_duplicate_clears_substitute_id():
    source = _email_missive(substitute_id="old-missive-ref")
    rec = MissiveRecipientEmail.objects.create(
        missive=source,
        name="Alice",
        email="alice@example.com",
        substitute_id="old-rec-ref",
    )
    clone = source.duplicate_missive()
    clone.refresh_from_db()
    assert clone.pk != source.pk
    assert clone.substitute_id is None
    cloned = clone.to_missiverecipient.get()
    assert cloned.pk != rec.pk
    assert cloned.substitute_id is None


def test_lookup_by_substitute_id():
    missive = _email_missive(substitute_id="legacy-custom-id")
    assert lookup_missive(uid="legacy-custom-id") == missive
    assert lookup_missive(partner_id="legacy-custom-id") == missive


def test_lookup_by_uid_still_matches_pk():
    missive = _email_missive()
    assert lookup_missive(uid=missive.pk) == missive
    assert lookup_missive(uid=str(missive.pk)) == missive


def test_form_accepts_non_uuid_uid():
    form = RetrieveMissiveForm(
        data={
            "provider": "maileva",
            "missive_type": MissiveType.REGISTERED_LETTER,
            "uid": "legacy-custom-id",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["uid"] == "legacy-custom-id"


def test_retrieve_stores_missive_and_recipient_substitute_id():
    uid = "legacy-sending-ref"
    response = {
        "external_id": "mv-sending-1",
        "custom_id": uid,
        "subject": "Imported",
        "recipients": [
            {
                "name": "Alice",
                "email": "alice@example.com",
                "external_id": "mv-rec-1",
                "substitute_id": "legacy-rec-ref",
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
            uid=uid,
        )
    assert created is True
    missive.refresh_from_db()
    assert missive.pk != uid
    assert missive.substitute_id == uid
    rec = missive.to_missiverecipient.get()
    assert rec.substitute_id == "legacy-rec-ref"
    assert rec.external_id == "mv-rec-1"


def test_retrieve_from_uid_without_custom_id_keeps_uid_as_substitute():
    uid = uuid4()
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={"external_id": "from-uid", "subject": "From uid", "events": []},
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            uid=uid,
        )
    assert created is True
    assert missive.substitute_id == str(uid)


def test_retrieve_does_not_store_pk_as_substitute_id():
    missive = _email_missive(external_id="ext-1")
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "ext-1",
            "custom_id": str(missive.pk),
            "subject": "Hello",
            "events": [],
        },
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    missive.refresh_from_db()
    assert missive.substitute_id is None


def test_provider_custom_id_prefers_substitute_then_id():
    assert _provider_custom_id({"substitute_id": "legacy", "id": "uuid"}) == "legacy"
    assert _provider_custom_id({"id": "uuid"}) == "uuid"
    assert _provider_custom_id({}) is None
    assert _provider_custom_id(None) is None


def _billing_provider():
    from pymissive.providers.maileva import MailevaProvider

    provider = MailevaProvider.__new__(MailevaProvider)
    provider.is_mode_sandbox = lambda: False
    provider.get_endpoint = (
        lambda endpoint, prefix="api": "https://api.maileva.com/billing/v1/recipient_items"
    )
    provider._get_headers = lambda: {}
    return provider


def test_get_billings_registered_letter_user_reference_is_substitute_id_not_external_id():
    from pymissive.providers.maileva import MailevaProvider

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"paging": {"total_results": 0}, "items": []}

    def fake_request(method, url, headers=None, timeout=None, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    with patch("pymissive.providers.maileva.requests.request", fake_request):
        MailevaProvider.get_billings_registered_letter(
            _billing_provider(),
            id="new-pk",
            substitute_id="753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            external_id="66188949-9f05-4503-ae1f-fe085bce3edb",
        )
    assert captured["url"].endswith("/billing/v1/recipient_items")
    assert captured["params"]["user_reference"] == "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"


def test_get_billings_registered_letter_user_reference_falls_back_to_missive_pk():
    from pymissive.providers.maileva import MailevaProvider

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"items": []}

    def fake_request(method, url, headers=None, timeout=None, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    with patch("pymissive.providers.maileva.requests.request", fake_request):
        MailevaProvider.get_billings_registered_letter(
            _billing_provider(),
            id="c880d57c-4dc8-4cd7-90dc-76c33b824ad6",
            substitute_id=None,
            external_id="66188949-9f05-4503-ae1f-fe085bce3edb",
        )
    assert captured["url"].endswith("/billing/v1/recipient_items")
    assert captured["params"]["user_reference"] == "c880d57c-4dc8-4cd7-90dc-76c33b824ad6"


def test_get_billings_registered_letter_returns_empty_when_not_invoiced():
    from pymissive.providers.maileva import MailevaProvider

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"paging": {"total_results": 0}, "items": []}

    with patch(
        "pymissive.providers.maileva.requests.request", lambda *a, **k: FakeResponse()
    ):
        billings = MailevaProvider.get_billings_registered_letter(
            _billing_provider(),
            id="pk",
            substitute_id="753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            external_id="sending-id",
        )
    assert billings == []

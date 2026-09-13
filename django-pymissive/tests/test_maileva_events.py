"""Maileva retrieve status codes and webhook event_types must both normalize."""

import pytest

from pymissive.providers.maileva import MailevaProvider

from django_pymissive.events import _process_event
from django_pymissive.models import MissiveEvent, MissiveRecipient, MissiveStatus, MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.utils import get_recipient


def _provider():
    return MailevaProvider.__new__(MailevaProvider)


def test_retrieve_processed_status_maps_to_processed():
    provider = _provider()
    payload = {
        "resource_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
        "event": "PROCESSED",
        "event_date": "2026-08-05T12:59:25Z",
        "recipient": {"id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"},
    }
    assert provider.get_normalize_event(payload) == "processed"
    assert provider.get_normalize_recipient(payload) == {
        "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
        "substitute_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
    }


def test_webhook_on_status_processed_still_maps():
    provider = _provider()
    payload = {
        "event_type": "ON_STATUS_PROCESSED",
        "resource_name": "recipients",
        "resource_custom_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
    }
    assert provider.get_normalize_event(payload) == "processed"
    assert provider.get_normalize_recipient(payload) == {
        "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
        "substitute_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
    }


def test_retrieve_status_codes_match_webhook_counterparts():
    provider = _provider()
    assert provider.get_normalize_event({"event": "ACCEPTED"}) == "accepted"
    assert provider.get_normalize_event({"event": "REJECTED"}) == "rejected"
    assert provider.get_normalize_event({"event": "PROCESSED_WITH_ERRORS"}) == "error"
    assert provider.get_normalize_event({"event": "ARCHIVED"}) == "archived"
    assert provider.get_normalize_event({"event": "PREPARING"}) == "processing"


def test_sending_level_webhook_has_no_recipient():
    provider = _provider()
    payload = {
        "event_type": "ON_STATUS_PROCESSED",
        "resource_name": "sendings",
        "resource_custom_id": "sending-custom-id",
    }
    assert provider.get_normalize_recipient(payload) is None


def test_serialize_recipient_statuses_keeps_processed_code():
    provider = _provider()
    events = provider._serialize_events_lre(
        [
            {
                "custom_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
                "id": "cba42db5-ed44-4688-a069-5fb4c78691ed",
                "address_line_2": "THE UNIQUE PAPER COMPANY LIMIT",
                "statuses": [
                    {"code": "ACCEPTED", "date": "2026-08-05T10:00:00Z"},
                    {"code": "PROCESSED", "date": "2026-08-05T12:59:25Z"},
                ],
            }
        ],
        {"id": "66188949-9f05-4503-ae1f-fe085bce3edb"},
    )
    assert events[-1] == {
        "resource_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
        "event": "PROCESSED",
        "event_date": "2026-08-05T12:59:25Z",
        "recipient": {
            "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            "substitute_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            "name": "THE UNIQUE PAPER COMPANY LIMIT",
        },
    }
    assert provider.get_normalize_event(events[-1]) == "processed"
    assert provider.get_normalize_external_id(events[-1]) == (
        "66188949-9f05-4503-ae1f-fe085bce3edb"
    )
    assert provider.get_normalize_recipient(events[-1]) == {
        "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
        "substitute_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
        "name": "THE UNIQUE PAPER COMPANY LIMIT",
    }


def test_event_external_id_is_sending_resource_id_not_recipient_uuid():
    provider = _provider()
    payload = {
        "resource_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
        "event": "PROCESSED",
        "recipient": {
            "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            "name": "THE UNIQUE PAPER COMPANY LIMIT",
        },
    }
    assert provider.get_normalize_external_id(payload) == (
        "66188949-9f05-4503-ae1f-fe085bce3edb"
    )


def test_recipient_level_webhook_does_not_use_recipient_uuid_as_missive_id():
    provider = _provider()
    payload = {
        "event_type": "ON_STATUS_PROCESSED",
        "resource_name": "recipients",
        "resource_id": "cba42db5-ed44-4688-a069-5fb4c78691ed",
        "resource_custom_id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
        "sending_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
    }
    assert provider.get_normalize_external_id(payload) == (
        "66188949-9f05-4503-ae1f-fe085bce3edb"
    )


def _lre_missive_with_address_recipient(**recipient_kw):
    missive = Missive.objects.create(
        missive_type=MissiveType.LRE,
        provider="maileva",
        subject="THE UNIQUE PAPER COMPANY LIMIT",
        sender_name="Octolo",
        status=MissiveStatus.PROCESSING,
        external_id="66188949-9f05-4503-ae1f-fe085bce3edb",
    )
    recipient = MissiveRecipient.objects.create(
        missive=missive,
        name="THE UNIQUE PAPER COMPANY LIMIT",
        recipient_support="address",
        external_id="cba42db5-ed44-4688-a069-5fb4c78691ed",
        **recipient_kw,
    )
    return missive, recipient


@pytest.mark.django_db
def test_get_recipient_uuid_custom_id_does_not_raise_and_matches_unique():
    missive, recipient = _lre_missive_with_address_recipient(
        substitute_id="753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"
    )
    found = get_recipient(
        missive, {"id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"}
    )
    assert found == recipient


@pytest.mark.django_db
def test_get_recipient_matches_substitute_id_among_several():
    missive, recipient = _lre_missive_with_address_recipient(
        substitute_id="753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Other",
        recipient_support="address",
        external_id="other-mv-id",
    )
    found = get_recipient(
        missive, {"id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"}
    )
    assert found == recipient


@pytest.mark.django_db
def test_get_recipient_matches_name():
    missive, recipient = _lre_missive_with_address_recipient()
    found = get_recipient(
        missive,
        {
            "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
            "name": "THE UNIQUE PAPER COMPANY LIMIT",
        },
    )
    assert found == recipient


@pytest.mark.django_db
def test_get_recipient_does_not_guess_among_several():
    missive, _first = _lre_missive_with_address_recipient()
    MissiveRecipient.objects.create(
        missive=missive,
        name="Other",
        recipient_support="address",
        external_id="other-mv-id",
    )
    assert get_recipient(
        missive, {"id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"}
    ) is None


@pytest.mark.django_db
def test_replay_processed_updates_unknown_event_and_attaches_recipient():
    missive, recipient = _lre_missive_with_address_recipient()
    stored = MissiveEvent.objects.create(
        missive=missive,
        event="unknown",
        reason="Unknown event.",
        occurred_at="2026-08-05T12:59:25Z",
        trace={
            "resource_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
            "event": "PROCESSED",
            "event_date": "2026-08-05T12:59:25Z",
            "recipient": {"id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686"},
        },
    )
    _process_event(
        {
            "event": "processed",
            "occurred_at": "2026-08-05T12:59:25Z",
            "external_id": "66188949-9f05-4503-ae1f-fe085bce3edb",
            "recipient": {
                "id": "753bdb3f-99d4-4e3e-91a9-ddf9b5dbd686",
                "name": "THE UNIQUE PAPER COMPANY LIMIT",
            },
            "raw": stored.trace,
        },
        missive,
        pk=stored.pk,
    )
    stored.refresh_from_db()
    assert stored.event == "processed"
    assert stored.recipient_id == recipient.pk

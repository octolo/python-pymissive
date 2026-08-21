"""Brevo bulk retrieve_events over a date range."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pymissive.providers.brevo import BrevoAPIProvider


def test_retrieve_events_email_paginates_and_normalizes_message_id():
    provider = BrevoAPIProvider()
    first_page = [
        {
            "messageId": f"<msg-{i}>",
            "email": "a@example.com",
            "event": "delivered",
            "date": "2026-08-20T10:00:00Z",
        }
        for i in range(2500)
    ]
    second_page = [
        {
            "message_id": "<msg-last>",
            "email": "b@example.com",
            "event": "opened",
            "date": "2026-08-20T11:00:00Z",
        }
    ]
    client = MagicMock()
    client.transactional_emails.get_email_event_report.side_effect = [
        SimpleNamespace(events=first_page),
        SimpleNamespace(events=second_page),
    ]
    provider._get_email_client = MagicMock(return_value=client)

    result = provider.retrieve_events(
        date(2026, 8, 20), date(2026, 8, 20), missive_type="email"
    )

    assert len(result["events"]) == 2501
    assert result["events"][0]["message_id"] == "<msg-0>"
    assert result["events"][-1]["message_id"] == "<msg-last>"
    assert client.transactional_emails.get_email_event_report.call_count == 2
    first_call = client.transactional_emails.get_email_event_report.call_args_list[0].kwargs
    assert first_call["start_date"] == "2026-08-20"
    assert first_call["end_date"] == "2026-08-20"
    assert first_call["limit"] == 2500
    assert first_call["offset"] == 0
    assert (
        client.transactional_emails.get_email_event_report.call_args_list[1].kwargs["offset"]
        == 2500
    )


def test_retrieve_email_chunks_from_created_at_and_filters_message_id():
    provider = BrevoAPIProvider()
    client = MagicMock()
    client.transactional_emails.get_email_event_report.side_effect = [
        SimpleNamespace(
            events=[
                {
                    "messageId": "<202605210817.1@x>",
                    "event": "delivered",
                    "date": "2026-05-21T08:17:00Z",
                }
            ]
        ),
        SimpleNamespace(
            events=[
                {
                    "messageId": "<202605210817.1@x>",
                    "event": "clicks",
                    "date": "2026-08-10T12:00:00Z",
                }
            ]
        ),
    ]
    provider._get_email_client = MagicMock(return_value=client)

    result = provider.retrieve_email(
        external_id="<202605210817.1@x>",
        created_at=datetime(2026, 5, 21, 8, 17, tzinfo=timezone.utc),
        end_date=date(2026, 8, 21),
    )

    assert [event["event"] for event in result["events"]] == ["delivered", "clicks"]
    calls = client.transactional_emails.get_email_event_report.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["message_id"] == "<202605210817.1@x>"
    assert calls[0].kwargs["start_date"] == "2026-05-21"
    assert calls[0].kwargs["end_date"] == "2026-08-19"
    assert calls[1].kwargs["start_date"] == "2026-08-20"
    assert calls[1].kwargs["end_date"] == "2026-08-21"


def test_retrieve_email_parses_date_from_brevo_message_id():
    provider = BrevoAPIProvider()
    client = MagicMock()
    client.transactional_emails.get_email_event_report.return_value = SimpleNamespace(
        events=[]
    )
    provider._get_email_client = MagicMock(return_value=client)

    provider.retrieve_email(
        external_id="<202605210817.30264662035@smtp-relay.mailin.fr>",
        end_date=date(2026, 8, 21),
    )

    first = client.transactional_emails.get_email_event_report.call_args_list[0].kwargs
    assert first["start_date"] == "2026-05-21"
    assert first["message_id"] == (
        "<202605210817.30264662035@smtp-relay.mailin.fr>"
    )


def test_retrieve_events_rejects_range_over_90_days():
    provider = BrevoAPIProvider()
    with pytest.raises(ValueError, match="90 days"):
        provider.retrieve_events(
            date(2026, 1, 1), date(2026, 4, 10), missive_type="email"
        )


def test_retrieve_events_sms_maps_phone_and_message_id():
    provider = BrevoAPIProvider()
    response = MagicMock()
    response.read.return_value = (
        b'{"events":[{"messageId":"sms-1","phoneNumber":"+33600000000",'
        b'"event":"delivered","date":"2026-08-20T10:00:00Z"}]}'
    )
    with patch("pymissive.providers.brevo.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = response
        result = provider.retrieve_events("2026-08-20", "2026-08-20", missive_type="sms")
    event = result["events"][0]
    assert event["message_id"] == "sms-1"
    assert event["phone"] == "+33600000000"
    assert event["event"] == "delivered"

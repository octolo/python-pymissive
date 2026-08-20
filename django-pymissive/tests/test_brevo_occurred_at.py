"""Brevo webhook vs retrieve timestamps must normalize to the same UTC instant."""

import json
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock

from django.utils.dateparse import parse_datetime

from django_pymissive.events import _get_occurred_at
from pymissive.providers.brevo import BrevoAPIProvider


def test_brevo_prefers_utc_timestamp_over_naive_account_date():
    provider = MagicMock()
    occurred = BrevoAPIProvider.get_normalize_occurred_at(
        provider,
        {
            "date": "2024-08-22 16:03:29",
            "ts_event": int(
                datetime(2024, 8, 22, 14, 3, 29, tzinfo=dt_timezone.utc).timestamp()
            ),
        },
    )
    assert _get_occurred_at(occurred) == datetime(
        2024, 8, 22, 14, 3, 29, tzinfo=dt_timezone.utc
    )


def test_brevo_retrieve_utc_date_matches_webhook_timestamp():
    provider = MagicMock()
    webhook = BrevoAPIProvider.get_normalize_occurred_at(
        provider,
        {
            "date": "2024-08-22 16:03:29",
            "ts_event": 1724335409,
        },
    )
    retrieve = BrevoAPIProvider.get_normalize_occurred_at(
        provider,
        {"date": "2024-08-22T14:03:29.000Z"},
    )
    assert _get_occurred_at(webhook) == _get_occurred_at(retrieve)


def test_send_email_normalize_does_not_insert_events_method():
    """send_email shares MISSIVE_FIELDS, including the ``events`` list field.

    Bulk retrieve lives on ``retrieve_events`` so getattr(provider, "events")
    must not yield a callable that ends up in the JSON trace.
    """
    provider = BrevoAPIProvider()
    provider._service_results_cache = {
        "send_email": {
            "result": {"message_id": "abc-123", "external_id": "abc-123"},
            "hash": "x",
        }
    }
    normalized = provider.get_service_normalize("send_email")
    assert not callable(normalized.get("events"))
    json.dumps(normalized)


def test_get_occurred_at_strips_microseconds():
    occurred = _get_occurred_at("2026-06-12T09:30:16.417Z")
    assert occurred.microsecond == 0
    assert occurred == parse_datetime("2026-06-12T09:30:16+00:00")

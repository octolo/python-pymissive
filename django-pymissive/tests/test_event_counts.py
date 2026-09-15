"""``get_event_counts`` classifies the latest event per recipient, in one query."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from django_pymissive.models import MissiveRecipientEmail
from django_pymissive.models.choices import MissiveStatus, MissiveType, status_from_event_counts
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db

BASE_TIME = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _missive() -> Missive:
    return Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        status=MissiveStatus.DRAFT,
    )


def _recipient(missive: Missive, email: str) -> MissiveRecipientEmail:
    return MissiveRecipientEmail.objects.create(missive=missive, email=email)


def _add_events(missive, recipient, events):
    """bulk_create keeps the billing post_save signal out of the query counts."""
    MissiveEvent.objects.bulk_create(
        [
            MissiveEvent(
                missive=missive,
                recipient=recipient,
                event=event,
                occurred_at=BASE_TIME + timedelta(minutes=offset),
            )
            for event, offset in events
        ]
    )


def test_only_the_latest_event_of_each_recipient_is_counted():
    missive = _missive()
    delivered = _recipient(missive, "ok@example.com")
    bounced = _recipient(missive, "ko@example.com")
    pending = _recipient(missive, "wait@example.com")

    _add_events(missive, delivered, [("sent", 0), ("delivered", 1)])
    _add_events(missive, bounced, [("delivered", 0), ("hard_bounce", 1)])
    _add_events(missive, pending, [("accepted", 0)])

    assert MissiveEvent.objects.get_event_counts(missive=missive) == (1, 1, 1, 0)


def test_missive_level_events_are_excluded():
    missive = _missive()
    recipient = _recipient(missive, "ok@example.com")
    _add_events(missive, recipient, [("delivered", 1)])
    _add_events(missive, None, [("request", 0)])

    assert MissiveEvent.objects.get_event_counts(missive=missive) == (1, 0, 0, 0)


def test_ties_on_occurred_at_resolve_to_the_row_inserted_last():
    missive = _missive()
    recipient = _recipient(missive, "ok@example.com")
    _add_events(missive, recipient, [("accepted", 0), ("delivered", 0)])

    assert MissiveEvent.objects.get_event_counts(missive=missive) == (1, 0, 0, 0)


def test_counts_are_scoped_to_a_single_recipient():
    missive = _missive()
    delivered = _recipient(missive, "ok@example.com")
    bounced = _recipient(missive, "ko@example.com")
    _add_events(missive, delivered, [("delivered", 0)])
    _add_events(missive, bounced, [("hard_bounce", 0)])

    assert MissiveEvent.objects.get_event_counts(recipient=delivered) == (1, 0, 0, 0)
    assert MissiveEvent.objects.get_event_counts(recipient=bounced) == (0, 0, 1, 0)


def test_counting_is_one_query_and_never_selects_the_json_columns(
    django_assert_num_queries,
):
    """The rows carry JSON trace/metadata; they must not be fetched to read ``event``."""
    missive = _missive()
    for index in range(5):
        recipient = _recipient(missive, f"r{index}@example.com")
        _add_events(missive, recipient, [("sent", 0), ("delivered", 1)])

    with django_assert_num_queries(1) as captured:
        MissiveEvent.objects.get_event_counts(missive=missive)

    sql = captured.captured_queries[0]["sql"]
    assert "trace" not in sql
    assert "metadata" not in sql


def test_cancelled_last_events_are_counted_apart_from_failures():
    missive = _missive()
    cancelled = _recipient(missive, "stop@example.com")
    bounced = _recipient(missive, "ko@example.com")
    _add_events(missive, cancelled, [("sent", 0), ("cancelled", 1)])
    _add_events(missive, bounced, [("hard_bounce", 0)])

    assert MissiveEvent.objects.get_event_counts(missive=missive) == (0, 0, 1, 1)
    assert MissiveEvent.objects.get_event_counts(recipient=cancelled) == (0, 0, 0, 1)


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ((0, 0, 0), MissiveStatus.DRAFT),
        ((0, 0, 0, 1), MissiveStatus.CANCELLED),
        ((0, 0, 1, 1), MissiveStatus.FAILED),
        ((1, 0, 0, 1), MissiveStatus.PARTIALLY_FAILED),
        ((0, 1, 0, 1), MissiveStatus.FAILED),
        ((2, 0, 0), MissiveStatus.SUCCESS),
        ((1, 1, 0), MissiveStatus.PARTIALLY_SUCCESS),
        ((0, 2, 0), MissiveStatus.PROCESSING),
        ((0, 0, 2), MissiveStatus.FAILED),
    ],
)
def test_status_from_event_counts(counts, expected):
    assert status_from_event_counts(*counts) == expected

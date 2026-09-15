"""HTTP contract of the webhook view.

The view used to answer 200 whatever happened, so any failure was a permanent
loss: the provider never retried. In particular a webhook overtaking the commit
of the missive it refers to vanished unless ``PYMISSIVE_SAVE_UNTREATED_EVENTS``
was on. Ingestion is idempotent, so asking for a retry is safe.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from django_pymissive.views.webhook import WebhookView

pytestmark = pytest.mark.django_db

EXTERNAL_ID = "7c9f1a52-0e2c-4a77-9a3f-2b2cf0c9d111"


def _url():
    return reverse("django_pymissive:missive_webhook", args=["brevo", "email"])


def _provider(normalized=None, raises=None):
    provider = MagicMock()
    provider.configure_mock(name="brevo")
    if raises is not None:
        provider._provider.call_service_formatted.side_effect = raises
    else:
        provider._provider.call_service_formatted.return_value = normalized
    return provider


def _event(external_id=EXTERNAL_ID):
    return {
        "external_id": external_id,
        "event": "delivered",
        "occurred_at": "2026-06-12T09:30:16Z",
        "raw": {},
    }


def _missive():
    return Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Sujet",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
        external_id=EXTERNAL_ID,
    )


def _post(provider):
    with patch.object(WebhookView, "get_object", return_value=provider):
        return Client().post(_url(), data=b"{}", content_type="application/json")


def test_a_processable_event_answers_200():
    missive = _missive()

    response = _post(_provider([_event()]))

    assert response.status_code == 200
    assert MissiveEvent.objects.filter(missive=missive, event="delivered").exists()


def test_a_payload_with_nothing_to_normalize_answers_200():
    response = _post(_provider([]))

    assert response.status_code == 200


def test_an_unknown_missive_asks_for_a_retry():
    """The usual cause is a webhook arriving before the missive is committed."""
    response = _post(_provider([_event(external_id="never-seen")]))

    assert response.status_code == 503


@override_settings(PYMISSIVE_SAVE_UNTREATED_EVENTS=True)
def test_an_unknown_missive_answers_200_once_parked():
    response = _post(_provider([_event(external_id="never-seen")]))

    assert response.status_code == 200
    assert MissiveEvent.objects.filter(missive__isnull=True).count() == 1


def test_an_unreadable_payload_answers_400():
    """No retry will make an unparseable body readable."""
    response = _post(_provider(raises=ValueError("not my format")))

    assert response.status_code == 400


def test_a_failing_event_asks_for_a_retry():
    _missive()

    with patch(
        "django_pymissive.events._process_event", side_effect=RuntimeError("boom")
    ):
        response = _post(_provider([_event()]))

    assert response.status_code == 503


def test_a_batch_keeps_the_good_events_and_still_asks_for_a_retry():
    missive = _missive()

    response = _post(_provider([_event(), _event(external_id="never-seen")]))

    assert response.status_code == 503
    assert MissiveEvent.objects.filter(missive=missive, event="delivered").exists()


def test_an_unknown_provider_answers_404():
    response = Client().post(
        reverse("django_pymissive:missive_webhook", args=["nope", "email"]),
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 404

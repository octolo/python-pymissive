"""Tests for the three send modes of ``Missive.send_missive``.

Covers the branching introduced for ``PYMISSIVE_DRY_RUN`` vs
``PYMISSIVE_DISABLE_SEND`` vs a real send:

- dry_run     → provider is NOT called, synthetic ``dry-run:`` external_id.
- disable_send→ provider IS called; a ``disabled_send`` response is persisted
                as a REQUEST event (never ERROR), like a real send.
- real send   → provider IS called and the response drives external_id/events.

The provider layer is mocked (``call_provider_service`` / ``get_serialized_data``)
so these tests stay at the Django orchestration layer with no external deps.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models import Missive, MissiveEvent, MissiveEventType, MissiveStatus
from django_pymissive.models.choices import MissiveType

pytestmark = pytest.mark.django_db


def _email_missive() -> Missive:
    return Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        body_text="Body",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )


def _events(missive: Missive):
    return list(MissiveEvent.objects.filter(missive=missive).order_by("pk"))


def test_dry_run_skips_provider(settings):
    settings.PYMISSIVE_DRY_RUN = True
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(Missive, "call_provider_service") as call_provider:
        missive.send_missive()

    call_provider.assert_not_called()
    missive.refresh_from_db()
    assert missive.external_id == f"dry-run:{missive.thread_id}"
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.REQUEST
    assert events[0].trace.get("dry_run") is True


def test_disable_send_calls_provider_and_records_request(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = True
    missive = _email_missive()

    disabled_response = {
        "external_id": None,
        "event": "disabled",
        "code": 200,
        "disabled_send": True,
        "message": "Send disabled (PYMISSIVE_DISABLE_SEND)",
    }

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive, "call_provider_service", return_value=dict(disabled_response)
    ) as call_provider:
        missive.send_missive()

    call_provider.assert_called_once()
    assert call_provider.call_args.args[0] == "send"

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.REQUEST
    assert events[0].trace.get("disabled_send") is True
    assert not any(e.event == MissiveEventType.ERROR for e in events)


def test_disable_send_persists_staged_external_id(settings):
    """A provider that staged the sending (e.g. Maileva) returns an external_id."""
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = True
    missive = _email_missive()

    staged_response = {
        "external_id": "staged-123",
        "event": "disabled",
        "disabled_send": True,
        "recipients": [],
        "attachments": [],
    }

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(Missive, "call_provider_service", return_value=dict(staged_response)):
        missive.send_missive()

    missive.refresh_from_db()
    assert missive.external_id == "staged-123"


def test_real_send_uses_provider_response(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    response = {
        "external_id": "ext-123",
        "event": "request",
        "recipients": [],
        "attachments": [],
    }

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive, "call_provider_service", return_value=dict(response)
    ) as call_provider:
        missive.send_missive()

    call_provider.assert_called_once()
    assert call_provider.call_args.args[0] == "send"

    missive.refresh_from_db()
    assert missive.external_id == "ext-123"
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.REQUEST
    assert not events[0].trace.get("dry_run")
    assert not events[0].trace.get("disabled_send")


def test_real_send_provider_exception_records_error_event(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive,
        "call_provider_service",
        side_effect=RuntimeError("provider timeout"),
    ):
        missive.send_missive()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.ERROR
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.ERROR
    assert events[0].trace.get("error") == "provider timeout"
    assert events[0].trace.get("error_type") == "RuntimeError"
    assert "RuntimeError: provider timeout" in events[0].trace.get("traceback", "")
    assert (missive.additional_config or {}).get("last_error") == "provider timeout"


def test_real_send_without_external_id_records_error_event(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    response = {"message": "Invalid API key", "code": 401}

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(Missive, "call_provider_service", return_value=dict(response)):
        missive.send_missive()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.ERROR
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.ERROR
    assert events[0].reason == "Invalid API key"
    assert events[0].trace.get("message") == "Invalid API key"


def test_send_failure_event_survives_atomic_block(settings):
    """ERROR event persists even when send_missive runs inside atomic()."""
    from django.db import transaction

    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive,
        "call_provider_service",
        side_effect=RuntimeError("provider timeout"),
    ):
        with transaction.atomic():
            missive.send_missive()

    missive.refresh_from_db()
    assert missive.status == MissiveStatus.ERROR
    events = _events(missive)
    assert len(events) == 1
    assert events[0].event == MissiveEventType.ERROR


def test_each_send_failure_appends_error_event(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_DISABLE_SEND = False
    missive = _email_missive()

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive,
        "call_provider_service",
        side_effect=RuntimeError("first failure"),
    ):
        missive.send_missive()

    with patch.object(Missive, "can_send", return_value=True), patch.object(
        Missive, "get_serialized_data", return_value={}
    ), patch.object(
        Missive,
        "call_provider_service",
        side_effect=RuntimeError("second failure"),
    ):
        missive.send_missive()

    events = _events(missive)
    assert len(events) == 2
    assert all(e.event == MissiveEventType.ERROR for e in events)
    assert events[0].trace.get("error") == "first failure"
    assert events[1].trace.get("error") == "second failure"
    assert missive.last_send_error() == "second failure"


def test_can_send_allows_error_retry_without_resend():
    missive = _email_missive()
    missive.status = MissiveStatus.ERROR
    missive.save(update_fields=["status"])

    with patch.object(Missive, "has_service", return_value=True), patch.object(
        missive, "check_email", return_value=True
    ):
        assert missive.can_send() is True

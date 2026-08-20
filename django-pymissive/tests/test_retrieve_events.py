"""Retrieve provider events between two dates from the event admin."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_pymissive.events import delay_retrieve_events, retrieve_events
from django_pymissive.forms.event import RetrieveEventsForm
from django_pymissive.models.choices import MissiveType

pytestmark = pytest.mark.django_db


def test_form_requires_dates():
    form = RetrieveEventsForm(
        data={"provider": "brevo", "missive_type": MissiveType.EMAIL}
    )
    assert form.is_valid() is False


def test_form_rejects_end_before_start():
    form = RetrieveEventsForm(
        data={
            "provider": "brevo",
            "missive_type": MissiveType.EMAIL,
            "start_date": "2026-02-01",
            "end_date": "2026-01-01",
        }
    )
    assert form.is_valid() is False


def test_form_accepts_range_and_as_task():
    form = RetrieveEventsForm(
        data={
            "provider": "brevo",
            "missive_type": MissiveType.EMAIL,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "as_task": "on",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["as_task"] is True
    assert form.cleaned_data["start_date"] == date(2026, 1, 1)
    assert form.cleaned_data["end_date"] == date(2026, 1, 31)


def test_retrieve_events_calls_provider_and_handles():
    provider = MagicMock()
    provider._provider = MagicMock()
    provider._provider.call_service.return_value = [{"event": "delivered"}]
    with patch(
        "django_pymissive.models.provider.MissiveProviderModel"
    ) as ProviderModel, patch("django_pymissive.events.handle_events") as handle:
        ProviderModel.objects.get.return_value = provider
        retrieve_events(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
    provider._provider.call_service.assert_called_once_with(
        "events_email",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    handle.assert_called_once()


def test_delay_retrieve_events_uses_sync_backend(settings):
    settings.CAMPAIGN_TASK_BACKEND = "sync"
    with patch("django_pymissive.events.retrieve_events") as retrieve:
        delay_retrieve_events(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
    retrieve.assert_called_once_with(
        provider="brevo",
        missive_type=MissiveType.EMAIL,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )


def test_delay_retrieve_events_uses_thread_backend(settings):
    settings.CAMPAIGN_TASK_BACKEND = "thread"
    with patch("django_pymissive.task.thread.Thread") as thread_cls:
        delay_retrieve_events(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
    thread_cls.assert_called_once()
    kwargs = thread_cls.call_args.kwargs
    assert kwargs["target"] is retrieve_events
    assert kwargs["kwargs"]["provider"] == "brevo"
    thread_cls.return_value.start.assert_called_once()


def test_admin_retrieve_events_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missiveevent_retrieve_events")
    response = client.get(url)
    assert response.status_code == 200
    assert b"start_date" in response.content or b"Start" in response.content


def test_admin_retrieve_events_post_sync():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missiveevent_retrieve_events")
    with patch("django_pymissive.admin.event.do_retrieve_events") as do_retrieve:
        response = client.post(
            url,
            {
                "provider": "brevo",
                "missive_type": MissiveType.EMAIL,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            },
        )
    do_retrieve.assert_called_once()
    assert response.status_code == 302
    assert "missiveevent" in response["Location"]


def test_admin_retrieve_events_post_as_task():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missiveevent_retrieve_events")
    with patch("django_pymissive.admin.event.delay_retrieve_events") as delay:
        response = client.post(
            url,
            {
                "provider": "brevo",
                "missive_type": MissiveType.EMAIL,
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "as_task": "on",
            },
        )
    delay.assert_called_once()
    assert response.status_code == 302

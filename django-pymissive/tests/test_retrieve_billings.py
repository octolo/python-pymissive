"""Retrieve provider billings between two dates from the billing admin."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from django_pymissive.billings import (
    _process_billing,
    delay_retrieve_billings,
    retrieve_billings,
)
from django_pymissive.forms.billing import RetrieveBillingsForm
from django_pymissive.models.billing import MissiveBilling
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def test_form_requires_dates():
    form = RetrieveBillingsForm(
        data={"provider": "maileva", "missive_type": MissiveType.REGISTERED_LETTER}
    )
    assert form.is_valid() is False


def test_form_rejects_end_before_start():
    form = RetrieveBillingsForm(
        data={
            "provider": "maileva",
            "missive_type": MissiveType.REGISTERED_LETTER,
            "start_date": "2026-02-01",
            "end_date": "2026-01-01",
        }
    )
    assert form.is_valid() is False


def test_form_accepts_range_and_as_task():
    form = RetrieveBillingsForm(
        data={
            "provider": "maileva",
            "missive_type": MissiveType.REGISTERED_LETTER,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "as_task": "on",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["as_task"] is True
    assert form.cleaned_data["start_date"] == date(2026, 1, 1)
    assert form.cleaned_data["end_date"] == date(2026, 1, 31)


def test_process_billing_updates_amount_on_the_same_invoice():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        external_id="send-amt",
        subject="registered letter",
    )
    _process_billing(
        missive,
        {
            "invoice": "INV-1",
            "billing_amount": 1.20,
            "estimate_amount": 1.20,
            "currency": "EUR",
        },
    )
    _process_billing(
        missive,
        {
            "invoice": "INV-1",
            "billing_amount": 1.35,
            "estimate_amount": 1.20,
            "currency": "EUR",
        },
    )
    assert MissiveBilling.objects.filter(missive=missive).count() == 1
    row = MissiveBilling.objects.get(missive=missive)
    assert float(row.billing_amount) == 1.35
    assert float(row.estimate_amount) == 1.20


def test_process_billing_keeps_distinct_invoices():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        external_id="send-two",
        subject="registered letter",
    )
    _process_billing(missive, {"invoice": "A", "billing_amount": 1.0})
    _process_billing(missive, {"invoice": "B", "billing_amount": 2.0})
    assert MissiveBilling.objects.filter(missive=missive).count() == 2


def test_retrieve_billings_calls_provider_and_upserts():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        external_id="send-1",
        substitute_id="sub-1",
        subject="registered letter",
    )
    provider = MagicMock()
    provider._provider = MagicMock()
    provider._provider.call_service.return_value = {
        "billings": [
            {
                "external_id": "send-1",
                "substitute_id": "sub-1",
                "billing_amount": 1.23,
                "estimate_amount": 1.23,
                "currency": "EUR",
                "invoice": "registered letter",
                "raw": {"amount": 1.23},
            }
        ]
    }
    with patch(
        "django_pymissive.models.provider.MissiveProviderModel"
    ) as ProviderModel:
        ProviderModel.objects.get.return_value = provider
        retrieve_billings(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
    provider._provider.call_service.assert_called_once_with(
        "retrieve_billings_registered_letter",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    billing = MissiveBilling.objects.get(missive=missive)
    assert float(billing.billing_amount) == 1.23
    assert billing.invoice == "registered letter"


def test_retrieve_billings_matches_substitute_id_when_no_external_id():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        substitute_id="sub-imported",
        subject="registered letter",
    )
    provider = MagicMock()
    provider._provider = MagicMock()
    provider._provider.call_service.return_value = [
        {
            "substitute_id": "sub-imported",
            "billing_amount": 2.0,
            "estimate_amount": 2.0,
            "currency": "EUR",
            "invoice": "AR",
        }
    ]
    with patch(
        "django_pymissive.models.provider.MissiveProviderModel"
    ) as ProviderModel:
        ProviderModel.objects.get.return_value = provider
        retrieve_billings(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
    assert MissiveBilling.objects.filter(missive=missive).count() == 1


def test_delay_retrieve_billings_uses_sync_backend(settings):
    settings.CAMPAIGN_TASK_BACKEND = "sync"
    with patch("django_pymissive.billings.retrieve_billings") as retrieve:
        delay_retrieve_billings(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
    retrieve.assert_called_once_with(
        provider="maileva",
        missive_type=MissiveType.REGISTERED_LETTER,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )


def test_delay_retrieve_billings_uses_thread_backend(settings):
    settings.CAMPAIGN_TASK_BACKEND = "thread"
    with patch("django_pymissive.task.thread.Thread") as thread_cls:
        delay_retrieve_billings(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
    thread_cls.assert_called_once()
    kwargs = thread_cls.call_args.kwargs
    assert kwargs["target"] is retrieve_billings
    assert kwargs["kwargs"]["provider"] == "maileva"
    thread_cls.return_value.start.assert_called_once()


def test_admin_retrieve_billings_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_retrieve_billings")
    response = client.get(url)
    assert response.status_code == 200
    assert b"start_date" in response.content or b"Start" in response.content


def test_admin_retrieve_billings_post_sync():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_retrieve_billings")
    with patch("django_pymissive.admin.billing.do_retrieve_billings") as do_retrieve:
        response = client.post(
            url,
            {
                "provider": "maileva",
                "missive_type": MissiveType.REGISTERED_LETTER,
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
            },
        )
    do_retrieve.assert_called_once()
    assert response.status_code == 302
    assert "missivebilling" in response["Location"]


def test_admin_retrieve_billings_post_as_task():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_retrieve_billings")
    with patch("django_pymissive.admin.billing.delay_retrieve_billings") as delay:
        response = client.post(
            url,
            {
                "provider": "maileva",
                "missive_type": MissiveType.REGISTERED_LETTER,
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "as_task": "on",
            },
        )
    delay.assert_called_once()
    assert response.status_code == 302

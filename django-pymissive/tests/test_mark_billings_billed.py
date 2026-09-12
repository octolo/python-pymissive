"""Mark stored billings as billed from the billing admin date form."""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_pymissive.billings import mark_billings_billed
from django_pymissive.models.billing import MissiveBilling
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _dt(year, month, day):
    naive = datetime(year, month, day, 12, 0, 0)
    if timezone.is_aware(timezone.now()):
        return timezone.make_aware(naive, dt_timezone.utc)
    return naive


def _billing(*, created_on, **kwargs):
    missive = kwargs.pop("missive", None) or Missive.objects.create(
        missive_type=MissiveType.LRE,
        subject="LRAR",
        external_id="ext-1",
        substitute_id="sub-1",
    )
    defaults = {
        "billing_amount": Decimal("1.2500"),
        "estimate_amount": Decimal("1.0000"),
        "currency": "EUR",
        "invoice": "LRE",
    }
    defaults.update(kwargs)
    billing = MissiveBilling.objects.create(missive=missive, **defaults)
    MissiveBilling.objects.filter(pk=billing.pk).update(created_at=_dt(*created_on))
    billing.refresh_from_db()
    return billing


def test_mark_billings_billed_updates_in_range_with_amount():
    in_range = _billing(created_on=(2026, 1, 15), is_billed=False)
    zero = _billing(
        created_on=(2026, 1, 16),
        billing_amount=Decimal("0.0000"),
        is_billed=False,
    )
    out_of_range = _billing(created_on=(2026, 2, 1), is_billed=False)
    updated = mark_billings_billed(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    in_range.refresh_from_db()
    zero.refresh_from_db()
    out_of_range.refresh_from_db()
    assert updated == 1
    assert in_range.is_billed is True
    assert zero.is_billed is False
    assert out_of_range.is_billed is False


def test_admin_mark_billed_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_mark_billed")
    response = client.get(url)
    assert response.status_code == 200
    assert b"start_date" in response.content or b"Start" in response.content


def test_admin_mark_billed_post_updates_and_redirects():
    billing = _billing(created_on=(2026, 8, 10), is_billed=False)
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_mark_billed")
    response = client.post(
        url,
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        },
    )
    assert response.status_code == 302
    assert "missivebilling" in response["Location"]
    billing.refresh_from_db()
    assert billing.is_billed is True

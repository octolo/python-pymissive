"""CSV export of stored billings from the billing admin."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django.http import StreamingHttpResponse

from django_pymissive.billings import billings_export_queryset, render_billings_csv
from django_pymissive.forms.billing import ExportBillingsForm
from django_pymissive.models.billing import MissiveBilling
from django_pymissive.models.choices import MissiveType
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient
from django_pymissive.models.related_object import MissiveRelatedObject
from tests.fakeapp.models import Category, Contact

pytestmark = pytest.mark.django_db


def _response_text(response):
    if getattr(response, "streaming_content", None) is not None:
        return b"".join(response.streaming_content).decode("utf-8-sig")
    return response.content.decode("utf-8-sig")


def _dt(year, month, day):
    naive = datetime(year, month, day, 12, 0, 0)
    if timezone.is_aware(timezone.now()):
        return timezone.make_aware(naive, dt_timezone.utc)
    return naive


def _billing(*, created_on, **kwargs):
    missive = kwargs.pop("missive", None) or Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="LRAR",
        external_id="ext-1",
        substitute_id="sub-1",
    )
    defaults = {
        "billing_amount": Decimal("1.2500"),
        "estimate_amount": Decimal("1.0000"),
        "currency": "EUR",
        "invoice": "registered letter",
    }
    defaults.update(kwargs)
    billing = MissiveBilling.objects.create(missive=missive, **defaults)
    MissiveBilling.objects.filter(pk=billing.pk).update(created_at=_dt(*created_on))
    billing.refresh_from_db()
    return billing


def test_export_form_requires_dates():
    form = ExportBillingsForm(data={})
    assert form.is_valid() is False


def test_export_form_rejects_end_before_start():
    form = ExportBillingsForm(
        data={"start_date": "2026-02-01", "end_date": "2026-01-01"}
    )
    assert form.is_valid() is False


def test_export_form_accepts_optional_filters():
    form = ExportBillingsForm(
        data={
            "provider": "maileva",
            "missive_type": MissiveType.REGISTERED_LETTER,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["start_date"] == date(2026, 1, 1)
    assert form.cleaned_data["end_date"] == date(2026, 1, 31)
    assert form.cleaned_data["fields"] == []
    assert form.cleaned_data["one_row"] is False


def test_queryset_filters_by_created_at():
    in_range = _billing(created_on=(2026, 1, 15))
    _billing(created_on=(2026, 2, 1))
    qs = billings_export_queryset(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    assert list(qs) == [in_range]


def test_csv_includes_recipient_and_amounts():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        external_id="ext-csv",
        substitute_id="sub-csv",
        provider="maileva",
    )
    recipient = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice Martin",
        email="alice@example.com",
        address={
            "address_line1": "10 rue Example",
            "postal_code": "75001",
            "city": "Paris",
            "country": "France",
        },
    )
    billing = _billing(
        created_on=(2026, 1, 10),
        missive=missive,
        recipient=recipient,
        is_billed=True,
    )
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert len(rows) == 2
    data = rows[1]
    assert str(missive.pk) in data
    assert "ext-csv" in data
    assert "sub-csv" in data
    assert "Facture" in data
    assert "Alice Martin" in data
    assert "alice@example.com" in data
    assert "10 rue Example" in data[11]
    assert "1.2500" in data
    assert "1" in data
    assert billing.invoice in data
    assert f"/admin/django_pymissive/missive/{missive.pk}/change/" in data[2]


def test_admin_export_csv_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_export_csv")
    response = client.get(url)
    assert response.status_code == 200
    assert b"start_date" in response.content or b"Start" in response.content


def test_admin_export_csv_post_downloads_file():
    _billing(created_on=(2026, 8, 10))
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_export_csv")
    response = client.post(
        url,
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        },
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "billings_2026-08-01_2026-08-31.csv" in response["Content-Disposition"]
    body = _response_text(response)
    assert "Billing Amount" in body or "1.2500" in body
    assert "1.2500" in body
    assert isinstance(response, StreamingHttpResponse)


def test_csv_without_extra_fields_does_not_resolve_related_objects():
    _billing(created_on=(2026, 1, 10))
    qs = billings_export_queryset(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    with patch(
        "django_pymissive.billings.related_objects_by_content_type"
    ) as related:
        csv_text = render_billings_csv(qs)
    related.assert_not_called()
    assert "1.2500" in csv_text


def test_export_form_accepts_related_object_fields():
    form = ExportBillingsForm(
        data={
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "fields": '["contact.last_name", "contact.category.name"]',
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["fields"] == [
        "contact.last_name",
        "contact.category.name",
    ]


def test_export_form_rejects_invalid_fields():
    form = ExportBillingsForm(
        data={
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "fields": '["contact.__class__"]',
        }
    )
    assert form.is_valid() is False
    assert "fields" in form.errors


def _billing_with_contact(*, last_name, category_name=None, created_on=(2026, 1, 10)):
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        external_id="ext-contact",
        substitute_id="sub-contact",
        provider="maileva",
    )
    category = None
    if category_name is not None:
        category = Category.objects.create(name=category_name)
    contact = Contact.objects.create(
        first_name="Alice",
        last_name=last_name,
        email="alice-export@example.com",
        category=category,
    )
    MissiveRelatedObject.objects.create(missive=missive, content_object=contact)
    return _billing(created_on=created_on, missive=missive)


def test_csv_includes_related_object_fields():
    _billing_with_contact(last_name="Martin", category_name="Pro")
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        extra_fields=["contact.last_name", "contact.category.name"],
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert rows[0][-2:] == ["contact.last_name.1", "contact.category.name.1"]
    assert rows[1][-2:] == ["Martin", "Pro"]


def test_csv_related_object_fields_empty_without_match():
    _billing(created_on=(2026, 1, 10))
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        extra_fields=["contact.last_name", "contact.category.name"],
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert rows[1][-2:] == ["", ""]


def test_csv_related_object_fields_expand_one_column_per_object():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        external_id="ext-multi",
        substitute_id="sub-multi",
    )
    pro = Category.objects.create(name="Pro")
    vip = Category.objects.create(name="VIP")
    first = Contact.objects.create(
        first_name="Alice",
        last_name="Martin",
        email="alice-multi@example.com",
        category=pro,
    )
    second = Contact.objects.create(
        first_name="Bob",
        last_name="Dupont",
        email="bob-multi@example.com",
        category=vip,
    )
    MissiveRelatedObject.objects.create(missive=missive, content_object=first)
    MissiveRelatedObject.objects.create(missive=missive, content_object=second)
    _billing(created_on=(2026, 1, 10), missive=missive)
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        extra_fields=["contact.last_name", "contact.category.name"],
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert rows[0][-4:] == [
        "contact.last_name.1",
        "contact.last_name.2",
        "contact.category.name.1",
        "contact.category.name.2",
    ]
    last_names = rows[1][-4:-2]
    category_names = rows[1][-2:]
    assert set(last_names) == {"Dupont", "Martin"}
    assert set(zip(last_names, category_names)) == {("Dupont", "VIP"), ("Martin", "Pro")}


def test_admin_export_csv_post_includes_related_fields():
    _billing_with_contact(last_name="Dupont", category_name="VIP", created_on=(2026, 8, 10))
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_export_csv")
    response = client.post(
        url,
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "fields": '["contact.last_name", "contact.category.name"]',
        },
    )
    assert response.status_code == 200
    body = _response_text(response)
    rows = list(csv.reader(StringIO(body)))
    assert "contact.last_name.1" in rows[0]
    assert "contact.category.name.1" in rows[0]
    assert "Dupont" in rows[1]
    assert "VIP" in rows[1]


def test_csv_one_row_pivots_invoice_labels_as_amount_columns():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        external_id="ext-pivot",
        substitute_id="sub-pivot",
        provider="maileva",
    )
    _billing(
        created_on=(2026, 1, 10),
        missive=missive,
        billing_amount=Decimal("1.2500"),
    )
    other = MissiveBilling.objects.create(
        missive=missive,
        billing_amount=Decimal("0.5000"),
        estimate_amount=Decimal("0.4000"),
        currency="EUR",
        invoice="AR",
    )
    MissiveBilling.objects.filter(pk=other.pk).update(created_at=_dt(2026, 1, 11))
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        one_row=True,
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert len(rows) == 2
    assert "registered letter" in rows[0]
    assert "AR" in rows[0]
    assert "Billing Amount" not in rows[0]
    assert "Invoice" not in rows[0]
    invoice_idx = rows[0].index("registered letter")
    ar_idx = rows[0].index("AR")
    assert rows[1][invoice_idx] == "1.2500"
    assert rows[1][ar_idx] == "0.5000"
    assert str(missive.pk) in rows[1]


def test_csv_one_row_sums_duplicate_invoice_labels():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        provider="maileva",
    )
    _billing(
        created_on=(2026, 1, 10),
        missive=missive,
        billing_amount=Decimal("1.0000"),
    )
    extra = MissiveBilling.objects.create(
        missive=missive,
        billing_amount=Decimal("0.2500"),
        currency="EUR",
        invoice="registered letter",
    )
    MissiveBilling.objects.filter(pk=extra.pk).update(created_at=_dt(2026, 1, 11))
    csv_text = render_billings_csv(
        billings_export_queryset(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        one_row=True,
    )
    rows = list(csv.reader(StringIO(csv_text)))
    assert len(rows) == 2
    assert rows[1][rows[0].index("registered letter")] == "1.2500"


def test_admin_export_csv_one_row_checkbox():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        subject="Facture",
        provider="maileva",
    )
    _billing(
        created_on=(2026, 8, 10),
        missive=missive,
        billing_amount=Decimal("2.0000"),
    )
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missivebilling_export_csv")
    response = client.post(
        url,
        {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "one_row": "on",
        },
    )
    assert response.status_code == 200
    rows = list(csv.reader(StringIO(_response_text(response))))
    assert "registered letter" in rows[0]
    assert rows[1][rows[0].index("registered letter")] == "2.0000"


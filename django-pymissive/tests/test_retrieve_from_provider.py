"""Retrieve a missive from provider partner ID or internal UID."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from django_pymissive.forms.missive import RetrieveMissiveForm
from django_pymissive.models import MissiveRecipient
from django_pymissive.models.choices import (
    AcknowledgementLevel,
    MissiveDeliveryMode,
    MissivePriority,
    MissiveRecipientType,
    MissiveStatus,
    MissiveType,
)
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from django_pymissive.retrieve import lookup_missive, retrieve_from_provider

pytestmark = pytest.mark.django_db


def _email_missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "body_text": "Body",
        "sender_name": "Octolo",
        "sender_email": "hello@example.com",
        "status": MissiveStatus.DRAFT,
        "provider": "brevo",
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_form_requires_partner_id_or_uid():
    form = RetrieveMissiveForm(
        data={"provider": "brevo", "missive_type": MissiveType.EMAIL}
    )
    assert form.is_valid() is False


def test_form_accepts_partner_id():
    form = RetrieveMissiveForm(
        data={
            "provider": "brevo",
            "missive_type": MissiveType.EMAIL,
            "partner_id": "msg-123",
        }
    )
    assert form.is_valid() is True
    assert form.cleaned_data["partner_id"] == "msg-123"


def test_form_has_no_level_fields():
    form = RetrieveMissiveForm()
    assert "acknowledgement" not in form.fields
    assert "delivery_mode" not in form.fields
    assert "priority" not in form.fields


def test_lookup_by_external_id():
    missive = _email_missive(external_id="ext-abc")
    found = lookup_missive(partner_id="ext-abc")
    assert found == missive


def test_lookup_partner_id_falls_back_to_uid():
    missive = _email_missive()
    found = lookup_missive(partner_id=str(missive.pk))
    assert found == missive


def test_lookup_by_uid():
    missive = _email_missive()
    found = lookup_missive(uid=missive.pk)
    assert found == missive


def test_lookup_unknown_partner_id_returns_none():
    assert lookup_missive(partner_id="not-a-uuid") is None


def test_retrieve_from_provider_form_creates_even_if_partner_id_exists():
    existing = _email_missive(external_id="ext-existing")
    response = {
        "external_id": "ext-existing",
        "subject": "New copy",
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        created_missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-existing",
        )
    assert created is True
    assert created_missive.pk != existing.pk
    assert Missive.objects.filter(external_id="ext-existing").count() == 2


def test_get_or_retrieve_creates_from_provider():
    response = {
        "external_id": "ext-new",
        "message_id": "ext-new",
        "subject": "Retrieved subject",
        "body_text": "Retrieved body",
        "sender_email": "from@example.com",
        "recipients": [{"email": "alice@example.com", "name": "Alice"}],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-new",
        )
    assert created is True
    missive.refresh_from_db()
    assert missive.external_id == "ext-new"
    assert missive.subject == "Retrieved subject"
    assert missive.body_text == "Retrieved body"
    assert missive.sender_email == "from@example.com"
    assert MissiveRecipient.objects.filter(
        missive=missive, email="alice@example.com"
    ).exists()
    rec = MissiveRecipient.objects.get(missive=missive, email="alice@example.com")
    assert rec.recipient_support == "email"
    assert missive.missive_support == "email"


def test_get_or_retrieve_creates_recipients_from_events():
    response = {
        "message_id": "ext-evt",
        "events": [
            {"email": "one@example.com", "event": "delivered"},
            {"email": "one@example.com", "event": "opened"},
            {"recipient": {"email": "two@example.com"}, "event": "sent"},
        ],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            partner_id="ext-evt",
        )
    assert created is True
    emails = set(
        MissiveRecipient.objects.filter(missive=missive).values_list("email", flat=True)
    )
    assert emails == {"one@example.com", "two@example.com"}


def test_retrieve_from_provider_form_sends_uid_without_reusing_it_as_pk():
    uid = uuid4()
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "from-uid",
            "subject": "From uid",
            "events": [],
        },
    ) as retrieve, patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="brevo",
            missive_type=MissiveType.EMAIL,
            uid=uid,
        )
    assert created is True
    assert missive.pk != uid
    assert retrieve.call_args.kwargs["internal_id"] == str(uid)
    assert missive.external_id == "from-uid"
    assert missive.substitute_id == str(uid)


def test_get_or_retrieve_does_not_create_when_not_found():
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={"message_id": "missing", "events": []},
    ):
        with pytest.raises(ValidationError, match="not found"):
            retrieve_from_provider(
                provider="brevo",
                missive_type=MissiveType.EMAIL,
                partner_id="missing",
            )
    assert Missive.objects.filter(external_id="missing").exists() is False


def test_get_or_retrieve_rejects_provider_without_retrieve():
    with patch.object(Missive, "has_service", return_value=False):
        with pytest.raises(ValidationError):
            retrieve_from_provider(
                provider="brevo",
                missive_type=MissiveType.EMAIL,
                partner_id="missing",
            )
    assert Missive.objects.filter(external_id="missing").exists() is False


def test_retrieve_does_not_forward_levels_to_provider():
    response = {
        "external_id": "ext-ar",
        "subject": "AR letter",
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ) as retrieve, patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            partner_id="ext-ar",
        )
    assert created is True
    kwargs = retrieve.call_args.kwargs
    assert "acknowledgement" not in kwargs
    assert "delivery_mode" not in kwargs
    assert "priority" not in kwargs
    assert kwargs["external_id"] == "ext-ar"


def test_admin_retrieve_get_renders_form():
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missive_retrieve_from_provider")
    response = client.get(url)
    assert response.status_code == 200
    assert b"partner_id" in response.content or b"Partner" in response.content


def test_admin_retrieve_post_creates_new_missive():
    existing = _email_missive(external_id="ext-admin")
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse("admin:django_pymissive_missive_retrieve_from_provider")
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "ext-admin",
            "subject": "From form",
            "events": [],
        },
    ), patch.object(Missive, "handle_events"):
        response = client.post(
            url,
            {
                "provider": "brevo",
                "missive_type": MissiveType.EMAIL,
                "partner_id": "ext-admin",
            },
        )
    assert response.status_code == 302
    assert str(existing.pk) not in response["Location"]
    assert Missive.objects.filter(external_id="ext-admin").count() == 2


def test_refresh_from_provider_updates_fields_and_creates_recipients():
    missive = _email_missive(external_id="ext-refresh", subject="Old")
    response = {
        "external_id": "ext-refresh",
        "subject": "Updated subject",
        "sender_email": "from@example.com",
        "recipients": [
            {
                "name": "Alice",
                "email": "alice@example.com",
                "external_id": "mv-1",
            }
        ],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    missive.refresh_from_db()
    assert missive.subject == "Updated subject"
    assert missive.sender_email == "from@example.com"
    rec = MissiveRecipient.objects.get(missive=missive)
    assert rec.email == "alice@example.com"
    assert rec.external_id == "mv-1"
    assert rec.recipient_support == "email"


def test_refresh_from_provider_keeps_notification_recipients():
    missive = _email_missive(external_id="ext-keep-notif", subject="Old")
    MissiveRecipient.objects.create(
        missive=missive,
        name="Ops",
        email="ops@example.com",
        recipient_type=MissiveRecipientType.NOTIFICATION,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Old recipient",
        email="old@example.com",
        recipient_type=MissiveRecipientType.RECIPIENT,
    )
    response = {
        "external_id": "ext-keep-notif",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com", "external_id": "mv-1"}
        ],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)

    emails = {
        (r.recipient_type, r.email)
        for r in MissiveRecipient.objects.filter(missive=missive)
    }
    assert emails == {
        (MissiveRecipientType.RECIPIENT, "alice@example.com"),
        (MissiveRecipientType.NOTIFICATION, "ops@example.com"),
    }


def test_refresh_from_provider_updates_only_fields_the_payload_provides():
    missive = _email_missive(
        external_id="ext-keep",
        subject="Old subject",
        body_text="Old body",
        body_rich="<p>Old</p>",
        sender_name="Old Sender",
        sender_email="old@example.com",
        reply_to_name="Old Reply",
        reply_to_email="reply@example.com",
        brand_name="OldBrand",
    )
    missive_pk = missive.pk
    response = {
        "external_id": "ext-other",
        "subject": "New subject",
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    missive.refresh_from_db()
    assert missive.pk == missive_pk
    assert missive.external_id == "ext-keep"
    assert missive.subject == "New subject"
    assert missive.body_text == "Old body"
    assert missive.body_rich == "<p>Old</p>"
    assert missive.sender_name == "Old Sender"
    assert missive.sender_email == "old@example.com"
    assert missive.reply_to_name == "Old Reply"
    assert missive.reply_to_email == "reply@example.com"
    assert missive.brand_name == "OldBrand"


def test_refresh_from_provider_keeps_metadata_context_and_processors():
    from django.contrib.contenttypes.models import ContentType

    from django_pymissive.models.campaign import MissiveCampaign
    from django_pymissive.models.related_object import MissiveRelatedObject
    from django_pymissive.models.scheduler import MissiveScheduledCampaign
    from tests.fakeapp.models import PdfDocument

    campaign = MissiveCampaign.objects.create(subject="Camp")
    scheduler = MissiveScheduledCampaign.objects.create(campaign=campaign)
    processors = [
        "django_pymissive.processors.body.django_template.django_template_processor"
    ]
    missive = _email_missive(
        external_id="ext-config",
        campaign=campaign,
        scheduler=scheduler,
        metadata={"source": "local"},
        additional_context={"foo": "bar"},
        additional_config={"use_provider_template": True},
        body_processors=processors,
        first_document_processors=list(processors),
        attachment_processors=list(processors),
    )
    doc = PdfDocument.objects.create(name="related")
    related = MissiveRelatedObject.objects.create(
        missive=missive,
        content_type=ContentType.objects.get_for_model(PdfDocument),
        object_id=doc.pk,
    )
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={"external_id": "ext-other", "subject": "From provider", "events": []},
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    missive.refresh_from_db()
    assert missive.subject == "From provider"
    assert missive.campaign_id == campaign.pk
    assert missive.scheduler_id == scheduler.pk
    assert missive.metadata == {"source": "local"}
    assert missive.additional_context == {"foo": "bar"}
    assert missive.additional_config == {"use_provider_template": True}
    assert missive.body_processors == processors
    assert missive.first_document_processors == processors
    assert missive.attachment_processors == processors
    assert MissiveRelatedObject.objects.filter(pk=related.pk, missive=missive).exists()


def test_refresh_from_provider_restores_billed_flag_on_recreated_billings():
    from decimal import Decimal

    from django_pymissive.models.billing import MissiveBilling

    missive = _email_missive(external_id="ext-billed")
    old = MissiveBilling.objects.create(
        missive=missive,
        billing_amount=Decimal("1.2500"),
        is_billed=True,
        currency="EUR",
    )

    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "ext-billed",
            "subject": "From provider",
            "recipients": [{"name": "Alice", "email": "alice@example.com"}],
            "events": [],
        },
    ), patch.object(Missive, "handle_events"), patch(
        "django_pymissive.billings.load_provider_billings",
        return_value=[
            {
                "billing_amount": Decimal("2.0000"),
                "currency": "EUR",
                "invoice": "INV-2",
            }
        ],
    ):
        retrieve_from_provider(missive=missive)
    assert not MissiveBilling.objects.filter(pk=old.pk).exists()
    billing = MissiveBilling.objects.get(missive=missive)
    assert billing.billing_amount == Decimal("2.0000")
    assert billing.is_billed is True


def test_refresh_from_provider_does_not_mark_unbilled_missive():
    from decimal import Decimal

    from django_pymissive.models.billing import MissiveBilling

    missive = _email_missive(external_id="ext-unbilled")
    MissiveBilling.objects.create(
        missive=missive,
        billing_amount=Decimal("1.0000"),
        is_billed=False,
    )

    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "external_id": "ext-unbilled",
            "subject": "From provider",
            "events": [],
        },
    ), patch.object(Missive, "handle_events"), patch(
        "django_pymissive.billings.load_provider_billings",
        return_value=[
            {
                "billing_amount": Decimal("3.0000"),
                "invoice": "INV-3",
            }
        ],
    ):
        retrieve_from_provider(missive=missive)
    billing = MissiveBilling.objects.get(missive=missive)
    assert billing.billing_amount == Decimal("3.0000")
    assert billing.is_billed is False


def test_refresh_from_provider_replaces_recipients_and_events():
    missive = _email_missive(external_id="ext-replace")
    kept_out = MissiveRecipient.objects.create(
        missive=missive,
        name="Local extra",
        email="extra@example.com",
        recipient_support="email",
    )
    old_rec = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        recipient_support="email",
        external_id="old-alice",
    )
    MissiveEvent.objects.create(
        missive=missive,
        recipient=old_rec,
        event="request",
        occurred_at=timezone.now(),
    )
    response = {
        "external_id": "ext-replace",
        "subject": "Refreshed",
        "recipients": [
            {
                "name": "Alice B",
                "email": "alice@example.com",
                "external_id": "mv-alice",
            }
        ],
        "events": [{"event": "delivered"}],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events") as handle_events:
        retrieve_from_provider(missive=missive)
    emails = set(
        MissiveRecipient.objects.filter(missive=missive).values_list("email", flat=True)
    )
    assert emails == {"alice@example.com"}
    rec = MissiveRecipient.objects.get(missive=missive)
    assert rec.pk != old_rec.pk
    assert rec.pk != kept_out.pk
    assert rec.name == "Alice B"
    assert rec.external_id == "mv-alice"
    assert missive.to_missiveevent.count() == 0
    handle_events.assert_called_once_with([{"event": "delivered"}])


def test_events_only_retrieve_keeps_body_recipients_and_billings():
    from decimal import Decimal

    from django_pymissive.models.billing import MissiveBilling

    missive = _email_missive(
        external_id="ext-events-only",
        subject="Keep me",
        body_text="Local body",
        body_rich="<p>Local</p>",
    )
    recipient = MissiveRecipient.objects.create(
        missive=missive,
        name="Alice",
        email="alice@example.com",
        recipient_support="email",
    )
    billing = MissiveBilling.objects.create(
        missive=missive,
        billing_amount=Decimal("4.0000"),
        currency="EUR",
        invoice="INV-KEEP",
    )
    local_event = MissiveEvent.objects.create(
        missive=missive,
        recipient=recipient,
        event="request",
        occurred_at=timezone.now(),
    )
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={
            "events": [
                {
                    "event": "accepted",
                    "occurred_at": "2026-06-12T09:30:16Z",
                    "external_id": "ext-events-only",
                }
            ]
        },
    ), patch.object(Missive, "handle_events") as handle_events, patch(
        "django_pymissive.billings.load_provider_billings",
        side_effect=RuntimeError("billing down"),
    ):
        retrieve_from_provider(missive=missive)

    missive.refresh_from_db()
    assert missive.subject == "Keep me"
    assert missive.body_text == "Local body"
    assert missive.body_rich == "<p>Local</p>"
    assert MissiveRecipient.objects.get(pk=recipient.pk).email == "alice@example.com"
    assert MissiveBilling.objects.get(pk=billing.pk).invoice == "INV-KEEP"
    handle_events.assert_called_once()
    assert not MissiveEvent.objects.filter(pk=local_event.pk).exists()


def test_refresh_from_provider_fills_missing_address_without_duplicating():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        provider="maileva",
        external_id="ext-addr",
        acknowledgement=AcknowledgementLevel.ACKNOWLEDGEMENT_OF_RECEIPT,
        status=MissiveStatus.PROCESSING,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Jean",
        external_id="mv-rec",
        recipient_support="address",
    )
    response = {
        "external_id": "ext-addr",
        "recipients": [
            {
                "name": "Jean Dupont",
                "external_id": "mv-rec",
                "address": {
                    "address_line1": "10 rue Example",
                    "postal_code": "75001",
                    "city": "Paris",
                    "country_code": "FR",
                },
            }
        ],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    assert MissiveRecipient.objects.filter(missive=missive).count() == 1
    rec = MissiveRecipient.objects.get(missive=missive)
    assert rec.name == "Jean Dupont"
    assert rec.external_id == "mv-rec"
    assert rec.address["address_line1"] == "10 rue Example"
    assert rec.address["city"] == "Paris"
    assert rec.recipient_support == "address"
    assert missive.missive_support == "address"


def test_retrieve_registered_letter_sets_address_support_on_missive_and_recipients():
    response = {
        "external_id": "ext-registered_letter-support",
        "subject": "LRAR",
        "recipients": [
            {
                "name": "Jean Dupont",
                "external_id": "mv-addr",
                "address": {
                    "address_line1": "10 rue Example",
                    "postal_code": "75001",
                    "city": "Paris",
                    "country_code": "FR",
                },
            }
        ],
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            partner_id="ext-registered_letter-support",
        )
    assert created is True
    assert missive.missive_support == "address"
    rec = MissiveRecipient.objects.get(missive=missive)
    assert rec.recipient_support == "address"
    assert rec.address["city"] == "Paris"


def test_retrieve_from_provider_maps_maileva_lines_to_geoaddress():
    from pymissive.providers.maileva import MailevaProvider

    provider = MailevaProvider.__new__(MailevaProvider)
    raw = {
        "id": "sending-fr",
        "name": "LRAR",
        "sender_address_line_1": "La Poste",
        "sender_address_line_2": "Service Courrier",
        "sender_address_line_4": "1 rue de la Paix",
        "sender_address_line_6": "75002 Paris",
        "sender_country_code": "FR",
        "recipients": [
            {
                "id": "d905a65e-aa46-4f37-8480-260c4600c810",
                "custom_id": "custom12234",
                "address_line_1": "La Poste",
                "address_line_2": "Me Eva DUPONT",
                "address_line_3": "Résidence des Peupliers",
                "address_line_4": "33 avenue de Paris",
                "address_line_5": "BP 356",
                "address_line_6": "75000 Paris",
                "country_code": "FR",
            }
        ],
        "events": [],
    }
    response = {
        "external_id": raw["id"],
        "subject": raw["name"],
        "sender_name": provider.get_normalize_sender_name(raw),
        "sender_address": provider.get_normalize_sender_address(raw),
        "recipients": provider.get_normalize_recipients(raw),
        "events": [],
    }
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive, "call_provider_service", return_value=response
    ), patch.object(Missive, "handle_events"):
        missive, created = retrieve_from_provider(
            provider="maileva",
            missive_type=MissiveType.REGISTERED_LETTER,
            partner_id="sending-fr",
        )
    assert created is True
    assert missive.sender_name == "Service Courrier"
    assert missive.sender_address["address_line1"] == "1 rue de la Paix"
    assert missive.sender_address["organization"] == "La Poste"
    rec = MissiveRecipient.objects.get(missive=missive)
    assert rec.name == "Me Eva DUPONT"
    assert rec.substitute_id == "custom12234"
    assert rec.address["organization"] == "La Poste"
    assert rec.address["address_line1"] == "33 avenue de Paris"
    assert rec.address["address_line2"] == "Résidence des Peupliers"
    assert rec.address["address_line3"] == "BP 356"
    assert rec.address["po_box"] == "BP 356"
    assert rec.address["postal_code"] == "75000"
    assert rec.address["city"] == "Paris"
    assert rec.address["country_code"] == "FR"
    assert "address_line_2" not in rec.address
    assert rec.address.get("name") is None


def test_refresh_from_provider_does_not_forward_levels():
    missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        provider="maileva",
        external_id="ext-levels",
        acknowledgement=AcknowledgementLevel.ACKNOWLEDGEMENT_OF_RECEIPT,
        delivery_mode=MissiveDeliveryMode.PREMIUM,
        priority=MissivePriority.URGENT,
        status=MissiveStatus.PROCESSING,
    )
    with patch.object(Missive, "has_service", return_value=True), patch.object(
        Missive,
        "call_provider_service",
        return_value={"external_id": "ext-levels", "subject": "X", "events": []},
    ) as retrieve, patch.object(Missive, "handle_events"):
        retrieve_from_provider(missive=missive)
    kwargs = retrieve.call_args.kwargs
    assert "acknowledgement" not in kwargs
    assert "delivery_mode" not in kwargs
    assert "priority" not in kwargs
    assert kwargs["external_id"] == "ext-levels"
    assert kwargs["internal_id"] == str(missive.pk)


def test_admin_refresh_from_provider_get_renders_confirm():
    missive = _email_missive(external_id="ext-confirm")
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse(
        "admin:django_pymissive_missive_refresh_from_provider", args=[missive.pk]
    )
    response = client.get(url)
    assert response.status_code == 200
    assert b"replace local data" in response.content
    assert b"external ID is kept" in response.content


def test_admin_refresh_from_provider_post_updates_missive():
    missive = _email_missive(external_id="ext-confirm-post", subject="Old")
    user = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="x"
    )
    client = Client()
    client.force_login(user)
    url = reverse(
        "admin:django_pymissive_missive_refresh_from_provider", args=[missive.pk]
    )
    with patch(
        "django_pymissive.admin.missive.do_retrieve_from_provider"
    ) as retrieve:
        retrieve.return_value = (missive, False)
        response = client.post(url, {"action": "confirm"})
    retrieve.assert_called_once()
    assert retrieve.call_args.kwargs["missive"] == missive
    assert response.status_code == 302
    assert str(missive.pk) in response["Location"]

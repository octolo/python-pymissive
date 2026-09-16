"""Smoke tests for the Django integration."""

import pytest
from django.apps import apps


def test_django_pymissive_app_loads():
    assert apps.is_installed("django_pymissive")
    assert apps.get_model("django_pymissive", "Missive")


@pytest.mark.django_db
def test_minimal_email_missive_flow():
    from django_pymissive.models import (
        Missive,
        MissiveEvent,
        MissiveEventType,
        MissiveRecipientEmail,
        MissiveStatus,
        MissiveType,
    )

    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Bienvenue chez Octolo",
        body_text="Bonjour Alice, ceci est un message de demonstration.",
        sender_name="Octolo",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )
    recipient = MissiveRecipientEmail.objects.create(
        missive=missive,
        name="Alice Martin",
        email="alice@example.com",
    )

    assert missive.missive_support == "email"
    assert missive.check_email() is True
    assert missive.recipients.count() == 1
    assert missive.first_recipient == recipient

    event = MissiveEvent.objects.create(
        missive=missive,
        recipient=recipient,
        event=MissiveEventType.SENT,
        client_initiated=True,
    )

    refreshed = Missive.objects.get(pk=missive.pk)
    assert event.reason
    assert refreshed.last_event == MissiveEventType.SENT
    assert refreshed.count_recipient == 1


@pytest.mark.django_db
def test_recipient_save_infers_support_from_email_and_missive_type():
    from django_pymissive.models import Missive, MissiveRecipient, MissiveType
    from django_pymissive.models.choices import MissiveStatus

    email_missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        body_text="Body",
        sender_email="hello@example.com",
        status=MissiveStatus.DRAFT,
    )
    by_email = MissiveRecipient.objects.create(
        missive=email_missive, name="Alice", email="alice@example.com"
    )
    assert by_email.recipient_support == "email"

    erl_missive = Missive.objects.create(
        missive_type=MissiveType.REGISTERED_LETTER,
        status=MissiveStatus.DRAFT,
    )
    by_missive = MissiveRecipient.objects.create(missive=erl_missive, name="Jean")
    assert erl_missive.missive_support == "address"
    assert by_missive.recipient_support == "address"

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

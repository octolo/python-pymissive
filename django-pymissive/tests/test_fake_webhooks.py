"""Random fake webhooks: shared runner, management command, admin task."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from django_pymissive.fake_webhooks import (
    OUTCOMES,
    FakeProviderDisabled,
    delay_fake_webhooks,
    run_fake_webhooks,
)
from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.event import MissiveEvent
from django_pymissive.models.missive import Missive
from django_pymissive.models.recipient import MissiveRecipient

pytestmark = pytest.mark.django_db


def _sent(external_id, *, provider="fake", status=MissiveStatus.PROCESSING):
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        provider=provider,
        status=status,
        external_id=external_id,
    )
    MissiveRecipient.objects.create(
        missive=missive,
        name="Ada",
        email="ada@example.com",
    )
    return missive


def test_a_sent_fake_missive_receives_a_webhook_and_changes_status(monkeypatch):
    missive = _sent("fake-email-1")
    monkeypatch.setattr(
        "django_pymissive.fake_webhooks.random.Random.choice",
        lambda *_args: "delivered",
    )

    result = run_fake_webhooks()

    missive.refresh_from_db()
    recipient = missive.to_missiverecipient.get()
    recipient.refresh_from_db()
    assert result["posted"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["url"].endswith("/webhook/fake/email/")
    assert result["results"][0]["events"] == ["delivered"]
    assert missive.status == MissiveStatus.SUCCESS
    assert recipient.status == MissiveStatus.SUCCESS
    assert MissiveEvent.objects.filter(missive=missive, event="delivered").exists()


def test_only_sent_fake_missives_are_posted(monkeypatch):
    sent = _sent("fake-email-sent")
    draft = _sent("fake-email-draft", status=MissiveStatus.DRAFT)
    other = _sent("brevo-1", provider="brevo")
    monkeypatch.setattr(
        "django_pymissive.fake_webhooks.random.Random.choice",
        lambda *_args: "error",
    )

    result = run_fake_webhooks()

    sent.refresh_from_db()
    draft.refresh_from_db()
    other.refresh_from_db()
    assert result["posted"] == 1
    assert sent.status == MissiveStatus.FAILED
    assert draft.status == MissiveStatus.DRAFT
    assert other.status == MissiveStatus.PROCESSING
    assert not MissiveEvent.objects.filter(missive=draft).exists()
    assert not MissiveEvent.objects.filter(missive=other).exists()


def test_a_cancelled_missive_is_left_alone(monkeypatch):
    cancelled = _sent("fake-cancelled", status=MissiveStatus.CANCELLED)
    monkeypatch.setattr(
        "django_pymissive.fake_webhooks.random.Random.choice",
        lambda *_args: "delivered",
    )

    result = run_fake_webhooks()

    cancelled.refresh_from_db()
    assert result["posted"] == 0
    assert cancelled.status == MissiveStatus.CANCELLED
    assert not MissiveEvent.objects.filter(missive=cancelled).exists()


def test_limit_keeps_the_oldest_missives():
    from datetime import timedelta

    from django.utils import timezone

    first = _sent("fake-1")
    second = _sent("fake-2")
    Missive.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=1))

    result = run_fake_webhooks(limit=1, seed=1)

    assert result["posted"] == 1
    assert result["results"][0]["missive_id"] == str(first.pk)
    assert result["results"][0]["events"][0] in OUTCOMES
    assert not MissiveEvent.objects.filter(missive=second).exists()


def test_the_same_seed_posts_the_same_event():
    _sent("fake-seed")

    first = run_fake_webhooks(seed=7)
    MissiveEvent.objects.all().delete()
    second = run_fake_webhooks(seed=7)

    assert first["results"][0]["events"] == second["results"][0]["events"]


def test_refuses_when_the_fake_provider_is_disabled(settings, monkeypatch):
    monkeypatch.delenv("PYMISSIVE_ALLOW_FAKE_PROVIDER", raising=False)
    settings.PYMISSIVE_ALLOW_FAKE_PROVIDER = False

    with pytest.raises(FakeProviderDisabled, match="PYMISSIVE_ALLOW_FAKE_PROVIDER"):
        run_fake_webhooks()


def test_the_command_prints_the_tally(capsys):
    _sent("fake-cmd")

    call_command("fake", seed=1)

    assert "Done: 1 posted, 0 failed." in capsys.readouterr().out


def test_the_command_refuses_when_the_fake_provider_is_disabled(settings, monkeypatch):
    monkeypatch.delenv("PYMISSIVE_ALLOW_FAKE_PROVIDER", raising=False)
    settings.PYMISSIVE_ALLOW_FAKE_PROVIDER = False

    with pytest.raises(CommandError, match="PYMISSIVE_ALLOW_FAKE_PROVIDER"):
        call_command("fake")


def test_delay_enqueues_the_shared_runner(monkeypatch):
    called = {}

    def record(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr("django_pymissive.fake_webhooks.run_fake_webhooks", record)

    delay_fake_webhooks(limit=2, seed=4)

    assert called == {"limit": 2, "seed": 4}


def _superuser():
    return get_user_model().objects.create_superuser(username="fake-admin", email="fake@example.com", password="x")


def test_the_admin_view_enqueues_the_task_and_updates_the_missive(monkeypatch):
    missive = _sent("fake-admin-1")
    monkeypatch.setattr(
        "django_pymissive.fake_webhooks.random.Random.choice",
        lambda *_args: "delivered",
    )
    client = Client()
    client.force_login(_superuser())
    url = reverse("admin:django_pymissive_missive_fake_webhooks")

    confirm = client.get(url)
    assert confirm.status_code == 200
    assert b"1" in confirm.content

    response = client.post(url, {"action": "confirm"})

    missive.refresh_from_db()
    assert response.status_code == 302
    assert missive.status == MissiveStatus.SUCCESS
    changelist = client.get(reverse("admin:django_pymissive_missive_changelist"))
    assert b"fake-webhooks" in changelist.content


def test_the_admin_button_is_hidden_when_fake_is_disabled(settings, monkeypatch):
    monkeypatch.delenv("PYMISSIVE_ALLOW_FAKE_PROVIDER", raising=False)
    settings.PYMISSIVE_ALLOW_FAKE_PROVIDER = False
    client = Client()
    client.force_login(_superuser())

    changelist = client.get(reverse("admin:django_pymissive_missive_changelist"))

    assert changelist.status_code == 200
    assert b"fake-webhooks" not in changelist.content


def test_the_admin_view_refuses_a_view_only_account():
    from django.contrib import admin
    from django.contrib.auth.models import Permission
    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory
    from django.contrib.messages.storage.fallback import FallbackStorage

    user = get_user_model().objects.create_user(username="viewer-fake", password="x", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_missive"))
    request = RequestFactory().post("/", {"action": "confirm"})
    request.user = get_user_model().objects.get(pk=user.pk)
    request.session = {}
    request._messages = FallbackStorage(request)
    missive_admin = admin.site._registry[Missive]

    with pytest.raises(PermissionDenied):
        missive_admin.fake_webhooks(request)

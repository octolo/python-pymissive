"""Webhook admin: provider filter is real, changelist needs no redirect."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.contrib import admin
from django.test import RequestFactory

from django_pymissive.admin.webhook import ProviderListFilter
from django_pymissive.models.webhook import MissiveWebhook

pytestmark = pytest.mark.django_db


def _qs(*rows):
    return MissiveWebhook.objects.queryset_class(
        model=MissiveWebhook, data=list(rows)
    )


def _webhook(*, webhook_id, provider_name, type="email"):
    obj = MissiveWebhook(
        webhook_id=webhook_id,
        type=type,
        url=f"https://example.com/missive/webhook/{provider_name}/{type}/",
    )
    obj.provider = MagicMock(name=provider_name)
    obj.provider.name = provider_name
    return obj


def test_provider_filter_keeps_only_the_selected_provider():
    request = RequestFactory().get("/", {"provider": "brevo"})
    filt = ProviderListFilter(request, request.GET.copy(), MissiveWebhook, None)
    qs = _qs(
        _webhook(webhook_id="brevo-1", provider_name="brevo"),
        _webhook(webhook_id="maileva-1", provider_name="maileva"),
    )
    filtered = list(filt.queryset(request, qs))
    assert [w.webhook_id for w in filtered] == ["brevo-1"]


def test_provider_filter_without_value_keeps_every_row():
    request = RequestFactory().get("/")
    filt = ProviderListFilter(request, request.GET.copy(), MissiveWebhook, None)
    qs = _qs(
        _webhook(webhook_id="brevo-1", provider_name="brevo"),
        _webhook(webhook_id="maileva-1", provider_name="maileva"),
    )
    assert len(list(filt.queryset(request, qs))) == 2


def test_changelist_without_provider_does_not_redirect():
    webhook_admin = admin.site._registry[MissiveWebhook]
    request = RequestFactory().get("/admin/django_pymissive/missivewebhook/")
    with patch.object(
        MissiveWebhook.objects, "all_providers", return_value=_qs()
    ) as all_providers:
        qs = webhook_admin.get_queryset(request)
    all_providers.assert_called_once()
    assert qs.count() == 0


def test_changelist_with_provider_uses_that_provider_only():
    webhook_admin = admin.site._registry[MissiveWebhook]
    request = RequestFactory().get("/", {"provider": "brevo"})
    scoped = _qs(_webhook(webhook_id="brevo-1", provider_name="brevo"))
    with patch.object(
        MissiveWebhook.objects, "get_queryset", return_value=scoped
    ) as get_qs:
        qs = webhook_admin.get_queryset(request)
    get_qs.assert_called_once_with("brevo")
    assert [w.webhook_id for w in qs] == ["brevo-1"]


def test_save_emits_signals_and_does_not_hit_virtualmodel_save():
    created = []

    def _on_save(sender, instance, **kwargs):
        created.append(instance.webhook_id)

    from django.db.models.signals import post_save

    post_save.connect(_on_save, sender=MissiveWebhook)
    try:
        webhook = MissiveWebhook(type="email")
        with patch.object(webhook, "new_webhook", return_value="brevo-99"):
            webhook.save()
        assert webhook.webhook_id == "brevo-99"
        assert created == ["brevo-99"]
    finally:
        post_save.disconnect(_on_save, sender=MissiveWebhook)

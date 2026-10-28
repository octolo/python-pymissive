"""Targeted ``Missive.save(update_fields=…)`` must not recompute defaults."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django_pymissive.models.choices import MissiveStatus, MissiveType
from django_pymissive.models.config import MissiveConfig
from django_pymissive.models.missive import Missive

pytestmark = pytest.mark.django_db


def _missive(**kwargs) -> Missive:
    defaults = {
        "missive_type": MissiveType.EMAIL,
        "subject": "Hello",
        "status": MissiveStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Missive.objects.create(**defaults)


def test_status_only_save_does_not_query_missive_config():
    missive = _missive()
    missive.status = MissiveStatus.PROCESSING
    with patch.object(MissiveConfig.objects, "filter") as filt:
        missive.save(update_fields=["status"])
    filt.assert_not_called()


def test_status_only_save_does_not_apply_or_discard_defaults(settings):
    settings.PYMISSIVE_DEFAULT_PROVIDER = None
    missive = _missive()
    MissiveConfig.objects.create(missive_type=MissiveType.EMAIL, default_provider="brevo")
    assert not missive.provider

    missive.status = MissiveStatus.PROCESSING
    missive.save(update_fields=["status"])
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.PROCESSING
    assert not missive.provider

    missive.save()
    missive.refresh_from_db()
    assert missive.provider == "brevo"


def test_settings_default_provider_fills_a_missing_config(settings):
    settings.PYMISSIVE_DEFAULT_PROVIDER = [
        "fake",
        {"email": "brevo"},
        {"sms": "smspartner"},
    ]
    email = _missive(missive_type=MissiveType.EMAIL)
    sms = _missive(missive_type=MissiveType.SMS, subject="Ping")
    letter = _missive(missive_type=MissiveType.LETTER, subject="Courrier")
    assert email.provider == "brevo"
    assert sms.provider == "smspartner"
    assert letter.provider == "fake"


def test_a_string_setting_is_the_provider_for_every_type(settings):
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    letter = _missive(missive_type=MissiveType.LETTER, subject="Courrier")
    assert letter.provider == "fake"


def test_force_fake_provider_overrides_every_type(settings):
    settings.PYMISSIVE_FORCE_FAKE_PROVIDER = True
    settings.PYMISSIVE_DEFAULT_PROVIDER = "brevo"
    MissiveConfig.objects.create(missive_type=MissiveType.EMAIL, default_provider="brevo")
    MissiveConfig.objects.create(missive_type=MissiveType.SMS, default_provider="smspartner")
    email = _missive(provider="sendgrid")
    sms = _missive(missive_type=MissiveType.SMS, subject="Ping")
    assert email.provider == "fake"
    assert sms.provider == "fake"


def test_missive_config_wins_over_the_settings_default(settings):
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    MissiveConfig.objects.create(
        missive_type=MissiveType.EMAIL,
        default_provider="brevo",
    )
    email = _missive()
    assert email.provider == "brevo"


def test_load_providers_writes_only_dict_entries(settings):
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    from django_pymissive.models.config import typed_default_providers

    settings.PYMISSIVE_DEFAULT_PROVIDER = [
        "fake",
        {"email": "brevo"},
        {"sms": "smspartner"},
    ]
    assert typed_default_providers() == {"email": "brevo", "sms": "smspartner"}
    settings.PYMISSIVE_DEFAULT_PROVIDER = "fake"
    assert typed_default_providers() == {}

    settings.PYMISSIVE_DEFAULT_PROVIDER = [
        "fake",
        {"email": "brevo"},
        {"sms": "smspartner"},
    ]
    user = get_user_model().objects.create_superuser(
        username="config-admin",
        email="config@example.com",
        password="x",
    )
    request = RequestFactory().get("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    model_admin = admin.site._registry[MissiveConfig]
    view = getattr(type(model_admin), "load_providers")

    payload = view(model_admin, request)
    assert "email → brevo" in str(payload["confirm"])
    assert "sms → smspartner" in str(payload["confirm"])
    assert "fake" not in str(payload["confirm"])

    view(model_admin, request, confirmed=True)
    assert MissiveConfig.objects.get(missive_type="email").default_provider == "brevo"
    assert MissiveConfig.objects.get(missive_type="sms").default_provider == "smspartner"
    assert MissiveConfig.objects.count() == 2


def test_load_providers_shows_what_it_replaces_and_skips_matching_rows(settings):
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.contrib.messages import get_messages
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    MissiveConfig.objects.create(missive_type="email", default_provider="sendgrid")
    MissiveConfig.objects.create(missive_type="sms", default_provider="smspartner")
    settings.PYMISSIVE_DEFAULT_PROVIDER = [
        {"email": "brevo"},
        {"sms": "smspartner"},
        {"letter": "maileva"},
    ]
    request = RequestFactory().get("/")
    request.user = get_user_model().objects.create_superuser(
        username="config-admin",
        email="config@example.com",
        password="x",
    )
    request.session = {}
    request._messages = FallbackStorage(request)
    model_admin = admin.site._registry[MissiveConfig]
    view = getattr(type(model_admin), "load_providers")

    confirm = str(view(model_admin, request)["confirm"])
    assert "email: sendgrid → brevo (replaced)" in confirm
    assert "letter → maileva (new)" in confirm
    assert "sms" not in confirm

    view(model_admin, request, confirmed=True)
    assert "1 configuration(s) created, 1 replaced, 1 unchanged." in [str(m) for m in get_messages(request)]
    assert MissiveConfig.objects.get(missive_type="email").default_provider == "brevo"

    confirm = str(view(model_admin, request)["confirm"])
    assert confirm == "Every configuration already matches PYMISSIVE_DEFAULT_PROVIDER."


def test_send_without_a_provider_says_so():
    from django.core.exceptions import ValidationError

    missive = Missive.objects.create(missive_type=MissiveType.EMAIL)
    Missive.objects.filter(pk=missive.pk).update(provider="")
    missive.refresh_from_db()
    with pytest.raises(ValidationError, match="no provider set"):
        missive.send_missive()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.DRAFT


def test_unusable_default_provider_entries_are_logged(settings, caplog):
    from django_pymissive.models.config import default_provider_for_type, typed_default_providers

    settings.PYMISSIVE_DEFAULT_PROVIDER = [
        "fake",
        "",
        42,
        {"emial": "brevo"},
        {"sms": ""},
        {"email": "brevo"},
    ]
    with caplog.at_level("WARNING", "django_pymissive.models.config"):
        assert typed_default_providers() == {"email": "brevo"}
    assert "ignored entry 42" in caplog.text
    assert "unknown missive type 'emial'" in caplog.text
    assert "empty provider for 'sms'" in caplog.text
    assert default_provider_for_type("sms") == "fake"


def test_full_save_still_fills_support_and_sender():
    missive = Missive(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        status=MissiveStatus.DRAFT,
    )
    missive.save()
    missive.refresh_from_db()
    assert missive.missive_support
    assert missive.acknowledgement
    assert missive.delivery_mode
    assert missive.priority

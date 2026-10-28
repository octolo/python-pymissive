"""Send-time recipient allow-list and override. Stored rows stay unchanged."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from django_pymissive.models import Missive, MissiveRecipientEmail, MissiveStatus
from django_pymissive.models.choices import MissiveRecipientType, MissiveType
from django_pymissive.utils import apply_send_recipients, disallowed_recipients

pytestmark = pytest.mark.django_db


def _email(address="alice@example.com", **kwargs):
    missive = Missive.objects.create(
        missive_type=MissiveType.EMAIL,
        subject="Hello",
        body_text="Body",
        status=MissiveStatus.DRAFT,
        **kwargs,
    )
    MissiveRecipientEmail.objects.create(missive=missive, name="Alice", email=address)
    return missive


def test_override_replaces_the_payload_and_keeps_the_row(settings, caplog):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"email": "donotdisturb@octolo.tech"}
    missive = _email()
    MissiveRecipientEmail.objects.create(
        missive=missive,
        name="Bob",
        email="bob@example.com",
        recipient_type=MissiveRecipientType.CC,
    )
    captured = {}

    def _call(service, **kwargs):
        captured["service"] = service
        captured["payload"] = kwargs
        return {"external_id": "ext-1"}

    with (
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "call_provider_service", side_effect=_call),
        caplog.at_level("WARNING", "django_pymissive.utils"),
    ):
        missive.send_missive()

    assert captured["service"] == "send"
    warnings = [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "alice@example.com -> donotdisturb@octolo.tech" in warnings[0]
    assert "bob@example.com -> donotdisturb@octolo.tech" in warnings[0]
    assert captured["payload"]["recipients"][0]["email"] == "donotdisturb@octolo.tech"
    assert captured["payload"]["recipients"][0]["name"] == "Alice"
    assert captured["payload"]["cc"][0]["email"] == "donotdisturb@octolo.tech"
    assert MissiveRecipientEmail.objects.get(missive=missive, name="Alice").email == "alice@example.com"


def test_allowed_recipient_is_kept_and_the_others_use_the_override(settings):
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"email": "donotdisturb@octolo.tech"}
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {"email": ["Staff@Octolo.tech"]}
    payload = {
        "recipients": [
            {"name": "Staff", "email": "staff@octolo.tech"},
            {"name": "Client", "email": "client@example.com"},
        ]
    }

    rewritten = apply_send_recipients(payload, "email")

    assert rewritten["recipients"][0]["email"] == "staff@octolo.tech"
    assert rewritten["recipients"][1]["email"] == "donotdisturb@octolo.tech"
    assert payload["recipients"][1]["email"] == "client@example.com"


def test_disallowed_recipient_without_override_raises_before_send(settings):
    settings.PYMISSIVE_DRY_RUN = False
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {}
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {"email": ["staff@octolo.tech"]}
    missive = _email("client@example.com")

    with (
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "call_provider_service") as call_provider,
        pytest.raises(ValidationError, match="client@example.com"),
    ):
        missive.send_missive()

    call_provider.assert_not_called()
    missive.refresh_from_db()
    assert missive.status == MissiveStatus.DRAFT


def test_missive_type_override_wins_over_the_support(settings):
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {
        "phone": "+33600000000",
        "sms": "+33611111111",
    }
    payload = {"recipients": [{"name": "Ada", "phone": "+33699999999"}]}

    rewritten = apply_send_recipients(payload, "sms")

    assert rewritten["recipients"][0]["phone"] == "+33611111111"


def test_allowed_path_keeps_staff_emails_and_overrides_the_others(settings):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    User.objects.create_user(username="ada", email="ada@octolo.tech", password="x", is_staff=True)
    User.objects.create_user(username="gone", email="gone@octolo.tech", password="x", is_staff=True, is_active=False)
    User.objects.create_user(username="client", email="client@example.com", password="x", is_staff=False)
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"email": "donotdisturb@octolo.tech"}
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {
        "email": "django_pymissive.processors.allowed.staff_emails",
    }
    payload = {
        "recipients": [
            {"email": "Ada@Octolo.tech"},
            {"email": "gone@octolo.tech"},
            {"email": "client@example.com"},
        ]
    }

    rewritten = apply_send_recipients(payload, "email")

    assert rewritten["recipients"][0]["email"] == "Ada@Octolo.tech"
    assert rewritten["recipients"][1]["email"] == "donotdisturb@octolo.tech"
    assert rewritten["recipients"][2]["email"] == "donotdisturb@octolo.tech"


def test_allowed_setting_may_be_the_staff_processor_itself(settings):
    from django.contrib.auth import get_user_model

    get_user_model().objects.create_user(username="ada", email="ada@octolo.tech", password="x", is_staff=True)
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"email": "donotdisturb@octolo.tech"}
    settings.PYMISSIVE_RECIPIENT_ALLOWED = "django_pymissive.processors.allowed.staff_emails"
    payload = {"recipients": [{"email": "ada@octolo.tech"}, {"email": "client@example.com"}]}

    rewritten = apply_send_recipients(payload, "email")

    assert rewritten["recipients"][0]["email"] == "ada@octolo.tech"
    assert rewritten["recipients"][1]["email"] == "donotdisturb@octolo.tech"


def test_allowed_dry_run_sends_only_when_every_recipient_is_allowed(settings, caplog):
    settings.PYMISSIVE_DRY_RUN = "allowed"
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {"email": ["ada@octolo.tech"]}
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"email": "donotdisturb@octolo.tech"}
    allowed = _email("ada@octolo.tech")
    blocked = _email("client@example.com")
    MissiveRecipientEmail.objects.create(
        missive=blocked,
        name="Copy",
        email="ada@octolo.tech",
        recipient_type=MissiveRecipientType.CC,
    )

    def _call(service, **kwargs):
        return {"external_id": "ext-1", "recipients": kwargs.get("recipients")}

    with (
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "call_provider_service", side_effect=_call) as call,
        caplog.at_level("WARNING", "django_pymissive.utils"),
    ):
        allowed.send_missive()
        blocked.send_missive()

    allowed.refresh_from_db()
    blocked.refresh_from_db()
    assert allowed.external_id == "ext-1"
    assert call.call_count == 1
    assert blocked.external_id == f"dry-run:{blocked.thread_id}"
    assert blocked.status != MissiveStatus.ERROR
    assert MissiveRecipientEmail.objects.get(missive=blocked, name="Alice").email == "client@example.com"
    events = list(blocked.to_missiveevent.all())
    assert events
    assert all(event.trace["dry_run"] == "allowed" for event in events)
    assert "client@example.com" in events[0].trace["blocked_recipients"]
    assert any("client@example.com" in record.getMessage() for record in caplog.records)


def test_allowed_dry_run_without_an_allow_list_stays_local(settings):
    settings.PYMISSIVE_DRY_RUN = "allowed"
    missive = _email("ada@octolo.tech")

    with (
        patch.object(Missive, "can_send", return_value=True),
        patch.object(Missive, "call_provider_service") as call,
    ):
        missive.send_missive()

    call.assert_not_called()
    missive.refresh_from_db()
    assert missive.external_id == f"dry-run:{missive.thread_id}"
    assert missive.to_missiveevent.get().trace["blocked_recipients"] == ["no allow-list"]


def test_admin_and_staff_email_lists_stay_separate():
    from django.contrib.auth import get_user_model

    from django_pymissive.processors.allowed import admin_emails, admin_staff_emails, staff_emails

    User = get_user_model()
    User.objects.create_user(username="staff", email="staff@octolo.tech", password="x", is_staff=True)
    User.objects.create_user(username="root", email="root@octolo.tech", password="x", is_superuser=True, is_staff=False)
    User.objects.create_user(username="client", email="client@example.com", password="x")
    User.objects.create_user(
        username="old",
        email="old@octolo.tech",
        password="x",
        is_superuser=True,
        is_active=False,
    )

    assert set(staff_emails()) == {"staff@octolo.tech"}
    assert set(admin_emails()) == {"root@octolo.tech"}
    assert set(admin_staff_emails()) == {"staff@octolo.tech", "root@octolo.tech"}


def test_address_must_match_an_allowed_entry(settings):
    staff = {"address_line1": "1 rue de la Paix", "postal_code": "75002", "city": "Paris"}
    client = {"address_line1": "9 rue du Client", "postal_code": "69001", "city": "Lyon"}
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {"address": [staff]}
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {"letter": staff}

    kept = apply_send_recipients({"recipients": [{"address": dict(staff)}]}, "letter")
    redirected = apply_send_recipients({"recipients": [{"address": client}]}, "letter")

    assert kept["recipients"][0]["address"] == staff
    assert redirected["recipients"][0]["address"]["city"] == "Paris"


def test_notification_allow_list_uses_the_exact_identifier(settings):
    settings.PYMISSIVE_RECIPIENT_ALLOWED = {"application": ["user-123"]}
    settings.PYMISSIVE_OVERRIDE_RECIPIENT = {}
    allowed = {"recipients": [{"notification_id": "user-123"}]}
    collision = {"recipients": [{"notification_id": "attacker-123"}]}

    assert apply_send_recipients(allowed, "notification") == allowed
    assert disallowed_recipients(allowed, "notification") == []
    assert disallowed_recipients(collision, "notification") == ["attacker-123"]
    with pytest.raises(ValidationError, match="attacker-123"):
        apply_send_recipients(collision, "notification")

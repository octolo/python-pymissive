"""Generic inbound webhook proof (Bearer, Basic, URL token)."""

from __future__ import annotations

import base64

from pymissive.webhook.auth import (
    authorization_matches,
    get_webhook_secret,
    verify_inbound_webhook,
)


def test_no_secret_accepts_anything():
    assert authorization_matches("", authorization="") is True
    assert authorization_matches("", authorization="Bearer nope") is True


def test_bearer_matches_the_secret():
    assert authorization_matches("s3cret", authorization="Bearer s3cret") is True
    assert authorization_matches("s3cret", authorization="bearer s3cret") is True
    assert authorization_matches("s3cret", authorization="Bearer other") is False


def test_basic_matches_on_password_only():
    raw = base64.b64encode(b"pymissive:s3cret").decode()
    other_login = base64.b64encode(b"anyone:s3cret").decode()
    wrong = base64.b64encode(b"pymissive:nope").decode()
    assert authorization_matches("s3cret", authorization=f"Basic {raw}") is True
    assert authorization_matches("s3cret", authorization=f"Basic {other_login}") is True
    assert authorization_matches("s3cret", authorization=f"Basic {wrong}") is False


def test_url_token_matches():
    assert authorization_matches("s3cret", url_token="s3cret") is True
    assert authorization_matches("s3cret", url_token="nope") is False
    assert authorization_matches("s3cret", authorization="", url_token="") is False


class _Provider:
    def __init__(self, secret=""):
        self.secret = secret

    def _get_config_or_env(self, key, default=None):
        return self.secret if key == "WEBHOOK_SECRET" else default


def test_verify_is_opt_in():
    assert verify_inbound_webhook(_Provider(""), authorization="") is True
    assert verify_inbound_webhook(_Provider("s3cret"), authorization="Bearer s3cret") is True
    assert verify_inbound_webhook(_Provider("s3cret"), authorization="") is False


def test_get_webhook_secret_strips():
    assert get_webhook_secret(_Provider("  abc  ")) == "abc"
    assert get_webhook_secret(object()) == ""


def test_brevo_owns_its_outbound_auth_payload():
    from unittest.mock import patch

    from pymissive.providers.brevo import BrevoAPIProvider

    provider = BrevoAPIProvider()
    with patch.object(provider, "get_webhook_secret", return_value="s3cret"):
        assert provider._webhook_auth_kwargs() == {
            "auth": {"type": "bearer", "token": "s3cret"},
        }


def test_maileva_create_sends_basic_when_secret_is_set():
    from unittest.mock import Mock

    from pymissive.providers.maileva import MailevaProvider

    posted = []

    class _Maileva(MailevaProvider):
        def _get_config_or_env(self, key, default=None):
            return "s3cret" if key == "WEBHOOK_SECRET" else default

        def get_endpoint(self, name, **kwargs):
            return "https://example.test/subscriptions"

        def _request(self, method, url, **kwargs):
            posted.append(kwargs.get("json"))
            resp = Mock()
            resp.raise_for_status = Mock()
            resp.json.return_value = {"id": "sub-1"}
            return resp

        def get_normalize_webhook_id(self, data):
            return data.get("id")

    _Maileva()._create_webhook_api(
        "https://app.test/missive/webhook/maileva/registered_letter/",
        ["ON_STATUS_ACCEPTED"],
        ["registered_mail/v4/sendings"],
    )
    assert posted[0]["authentication"]["basic"]["password"] == "s3cret"
    assert posted[0]["authentication"]["basic"]["login"] == "pymissive"
    assert posted[0]["callback_url"].endswith("/maileva/registered_letter/")


def test_maileva_create_uses_configured_basic_login():
    from unittest.mock import Mock

    from pymissive.providers.maileva import MailevaProvider

    posted = []

    class _Maileva(MailevaProvider):
        def _get_config_or_env(self, key, default=None):
            if key == "WEBHOOK_SECRET":
                return "s3cret"
            if key == "WEBHOOK_BASIC_LOGIN":
                return "octolo"
            return default

        def get_endpoint(self, name, **kwargs):
            return "https://example.test/subscriptions"

        def _request(self, method, url, **kwargs):
            posted.append(kwargs.get("json"))
            resp = Mock()
            resp.raise_for_status = Mock()
            resp.json.return_value = {"id": "sub-1"}
            return resp

        def get_normalize_webhook_id(self, data):
            return data.get("id")

    _Maileva()._create_webhook_api(
        "https://app.test/hook",
        ["ON_STATUS_ACCEPTED"],
        ["registered_mail/v4/sendings"],
    )
    assert posted[0]["authentication"]["basic"]["login"] == "octolo"


def test_maileva_blank_basic_login_uses_its_default():
    from pymissive.providers.maileva import MailevaProvider

    class _Maileva(MailevaProvider):
        def _get_config_or_env(self, key, default=None):
            if key == "WEBHOOK_SECRET":
                return "s3cret"
            if key == "WEBHOOK_BASIC_LOGIN":
                return "   "
            return default

    assert _Maileva()._webhook_authentication() == {
        "basic": {"login": "pymissive", "password": "s3cret"},
    }


def test_scaleway_asks_for_a_url_token():
    from pymissive.providers.brevo import BrevoAPIProvider
    from pymissive.providers.maileva import MailevaProvider
    from pymissive.providers.scaleway import ScalewayProvider

    class _NoConfig:
        def _get_config_or_env(self, key, default=None):
            return default

    class S(_NoConfig, ScalewayProvider):
        pass

    class B(_NoConfig, BrevoAPIProvider):
        pass

    class M(_NoConfig, MailevaProvider):
        pass

    assert S().webhook_uses_url_token() is True
    assert B().webhook_uses_url_token() is False
    assert M().webhook_uses_url_token() is False


def test_create_webhook_email_subscribes_only_to_transactional_events():
    from unittest.mock import MagicMock

    from pymissive.providers.brevo import BrevoAPIProvider

    class _NoConfig:
        def _get_config_or_env(self, key, default=None):
            return default

    class B(_NoConfig, BrevoAPIProvider):
        pass

    provider = B()
    client = MagicMock()
    client.webhooks.create_webhook.return_value = MagicMock(id=42)
    provider._get_webhooks_client = lambda: client
    provider.create_webhook_email({"url": "https://example.com/hook"})
    events = client.webhooks.create_webhook.call_args.kwargs["events"]
    assert "sent" in events
    assert "delivered" in events
    assert "accepted" not in events
    assert "loadedByProxy" not in events
    assert "error" not in events

from __future__ import annotations

import base64
import json
import sys
import types
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.error import HTTPError

import pytest

from pymissive.providers.brevo import BrevoAPIProvider
from pymissive.providers.discord import DiscordProvider
from pymissive.providers.partner import PartnerProvider
from pymissive.providers.scaleway import ScalewayProvider
from pymissive.webhook_auth import authorization_matches, get_webhook_basic_login


def _provider(cls, **values):
    defaults = getattr(cls, "config_defaults", {}) or {}

    class Configured(cls):
        def _get_config_or_env(self, key, default=None):
            if key in values:
                return values[key]
            return defaults.get(key, default)

    return Configured()


class _Response:
    def __init__(self, payload, *, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.raise_for_status = Mock()

    def json(self):
        return self.payload


class _Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_webhook_auth_rejects_malformed_and_unknown_authorization():
    malformed = base64.b64encode(b"no-colon").decode()

    assert authorization_matches("secret", authorization="Digest abc") is False
    assert authorization_matches("secret", authorization="Bearer") is False
    assert authorization_matches("secret", authorization="Basic !!!") is False
    assert authorization_matches("secret", authorization=f"Basic {malformed}") is False


def test_webhook_basic_login_falls_back_for_blank_value():
    provider = Mock()
    provider._get_config_or_env.return_value = "   "

    assert get_webhook_basic_login(provider) == "pymissive"


def test_partner_request_places_get_data_in_query_and_post_data_in_json():
    provider = _provider(PartnerProvider)
    response = _Response({"ok": True})

    with patch("pymissive.providers.partner.requests.request", return_value=response) as request:
        assert provider._request("https://example.test", "GET", {"a": 1}) == {"ok": True}
        get_kwargs = request.call_args.kwargs
        assert get_kwargs["params"] == {"a": 1}
        assert "json" not in get_kwargs

        provider._request("https://example.test", "PATCH", {"b": 2})
        post_kwargs = request.call_args.kwargs
        assert post_kwargs["json"] == {"b": 2}
        assert "params" not in post_kwargs


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"event": "delivered"}, "delivered"),
        ({"event": 1}, "unknown"),
        ({"status": "not delivered"}, "failed"),
        ({"status": None}, "unknown"),
        ({"success": True}, "sent"),
        ({"success": False}, "failed"),
        ({}, "unknown"),
    ],
)
def test_partner_normalizes_event_variants(payload, expected):
    assert _provider(PartnerProvider).get_normalize_event(payload) == expected


def test_partner_normalizes_recipients_events_invoice_and_time():
    provider = _provider(PartnerProvider)

    assert provider.get_normalize_recipient({"phoneNumber": "+331"}) == {"phone": "+331"}
    assert provider.get_normalize_recipient({"phone": "+332"}) == {"phone": "+332"}
    assert provider.get_normalize_recipient({}) is None
    assert provider.get_normalize_events({"message_id": "m1", "events": [{"phone": "+331", "status": "sent"}]}) == [
        {
            "message_id": "m1",
            "phone": "+331",
            "status": "sent",
            "recipient": {"phone": "+331"},
        }
    ]
    assert provider.get_normalize_events({}) is None
    assert provider.get_normalize_invoice({"nbSms": 2}) == "nbSms: 2"
    assert provider.get_normalize_invoice({}) is None
    assert provider.get_normalize_occurred_at({"date": 0})[:4].isdigit()
    assert provider.get_normalize_billings({"cost": 1}) == [{"cost": 1}]


def test_partner_retrieve_billings_and_webhook_paths():
    provider = _provider(PartnerProvider, SMS_API_KEY="key")
    statuses = {"StatutResponse_List": [{"phone": "+331", "cost": 0.1}]}

    with patch.object(provider, "_request", return_value=statuses) as request:
        assert provider.retrieve_sms(external_id="m1") == {
            "message_id": "m1",
            "events": statuses["StatutResponse_List"],
        }
        assert request.call_args.args[1] == "GET"
        assert provider.get_billings_sms(external_id="m1") == [{"phone": "+331", "cost": 0.1, "message_id": "m1"}]

    with patch.object(provider, "_retrieve_sms", return_value={}):
        assert provider.get_billings_sms(external_id="m1") is None
    assert provider.handle_webhook_sms(b'{"status": "sent"}') == {"status": "sent"}
    payload = [{"status": "sent"}]
    assert provider.handle_webhook_sms(payload) is payload


def _discord_module(*, cached_channel):
    module = types.ModuleType("discord")
    channel = SimpleNamespace(id=456)
    channel.send = AsyncMock(return_value=SimpleNamespace(id=123))

    class Intents:
        @staticmethod
        def none():
            return "none"

    class Client:
        def __init__(self, *, intents):
            self.intents = intents
            self.ready = None
            self.closed = False

        def event(self, callback):
            self.ready = callback
            return callback

        def get_channel(self, channel_id):
            return channel if cached_channel else None

        async def fetch_channel(self, channel_id):
            return channel

        async def close(self):
            self.closed = True

        async def start(self, token):
            await self.ready()

    module.Intents = Intents
    module.Client = Client
    return module, channel


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"channel_id": 1}, "1"),
        ({"recipients": [{"channel_id": 2}]}, "2"),
        ({"recipients": [{"id": 3}]}, "3"),
        ({"recipients": [{"channel": 4}]}, "4"),
    ],
)
def test_discord_resolves_channel_variants(kwargs, expected):
    assert _provider(DiscordProvider)._resolve_channel_id(**kwargs) == expected


@pytest.mark.parametrize("cached_channel", [True, False])
def test_discord_sends_through_cached_or_fetched_channel(monkeypatch, cached_channel):
    discord, channel = _discord_module(cached_channel=cached_channel)
    monkeypatch.setitem(sys.modules, "discord", discord)
    provider = _provider(DiscordProvider, DISCORD_BOT_TOKEN="token", DISCORD_CHANNEL_ID="456")

    assert provider.send_branded(body_rich="hello") == {
        "id": "123",
        "channel_id": "456",
        "status": "sent",
    }
    channel.send.assert_awaited_once_with("hello")


def test_discord_wraps_sdk_failure(monkeypatch):
    discord, channel = _discord_module(cached_channel=True)

    async def fail(content):
        raise ValueError("denied")

    channel.send.side_effect = fail
    monkeypatch.setitem(sys.modules, "discord", discord)

    with pytest.raises(RuntimeError, match="Discord SDK error: denied"):
        _provider(DiscordProvider, DISCORD_BOT_TOKEN="token", DISCORD_CHANNEL_ID="456").send_branded(subject="hello")


def test_brevo_normalization_helpers_cover_object_shapes():
    provider = _provider(BrevoAPIProvider)

    assert provider.get_normalize_type({"type": "transactional"}) == "email"
    assert provider.get_normalize_type({"type": "marketing"}) == "email_marketing"
    assert provider.get_normalize_type({"type": "sms"}) == "sms"
    assert provider.get_normalize_type({}) == "unknown"
    assert provider.get_normalize_events({"events": [{"phone": "+331"}]}) == [
        {"phone": "+331", "recipient": {"phone": "+331"}}
    ]
    assert provider.get_normalize_events({}) is None
    assert provider.get_normalize_occurred_at({"trace": {"ts": 1_700_000_000_000}}).endswith("+00:00")
    assert provider.get_normalize_occurred_at({"date": "2026-01-01"}) == "2026-01-01"
    assert provider.get_normalize_occurred_at({}) is None

    model = SimpleNamespace(model_dump=lambda: {"messageId": "m1", "phoneNumber": "+331"})

    class Legacy:
        def dict(self):
            return {"message_id": "m2"}

    plain = SimpleNamespace(message_id="m3", _private="ignored")
    assert provider._event_to_payload(model) == {
        "messageId": "m1",
        "phoneNumber": "+331",
        "message_id": "m1",
        "phone": "+331",
    }
    assert provider._event_to_payload(Legacy())["message_id"] == "m2"
    assert provider._event_to_payload(plain) == {"message_id": "m3"}


def test_brevo_date_validation_chunking_and_message_id_date():
    provider = _provider(BrevoAPIProvider)

    assert provider._report_date_range(date(2026, 1, 1), date(2026, 1, 2)) == ("2026-01-01", "2026-01-02")
    with pytest.raises(ValueError, match="on or after"):
        provider._report_date_range("2026-01-02", "2026-01-01")
    with pytest.raises(ValueError, match="90 days"):
        provider._report_date_range("2026-01-01", "2026-04-02")
    assert list(provider._event_report_date_chunks("2026-01-03", "2026-01-01", max_days=1)) == [
        (date(2026, 1, 1), date(2026, 1, 2)),
        (date(2026, 1, 3), date(2026, 1, 3)),
    ]
    assert provider._date_from_brevo_message_id("<20260521.id@example>") == date(2026, 5, 21)
    assert provider._date_from_brevo_message_id("<20261340.id@example>") is None
    assert provider._date_from_brevo_message_id(None) is None


def test_brevo_retrieve_email_uses_chunks_and_message_id_date():
    provider = _provider(BrevoAPIProvider)
    provider._retrieve_email_event_report = MagicMock(side_effect=[[{"event": "sent"}], []])

    result = provider.retrieve_email(external_id="<20260101.id@example>", end_date="2026-04-02", tags="invoice")

    assert result == {"message_id": "<20260101.id@example>", "events": [{"event": "sent"}]}
    assert provider._retrieve_email_event_report.call_count == 2
    assert provider._retrieve_email_event_report.call_args_list[0].kwargs["message_id"] == "<20260101.id@example>"


def test_brevo_email_report_paginates_and_converts_dict_response():
    provider = _provider(BrevoAPIProvider)
    client = MagicMock()
    first_page = [{"messageId": f"m{i}"} for i in range(2500)]
    client.transactional_emails.get_email_event_report.side_effect = [
        {"events": first_page},
        {"events": [{"message_id": "last"}]},
    ]
    provider._get_email_client = MagicMock(return_value=client)

    events = provider._retrieve_email_event_report("2026-01-01", "2026-01-02", message_id="m", tags="invoice")

    assert len(events) == 2501
    assert events[0]["message_id"] == "m0"
    assert client.transactional_emails.get_email_event_report.call_args_list[1].kwargs["offset"] == 2500


def test_brevo_sms_report_paginates_and_surfaces_http_error():
    provider = _provider(BrevoAPIProvider, SMS_API_KEY="sms-key")
    pages = [_Body({"events": [{"messageId": str(i)} for i in range(100)]}), _Body({"events": []})]

    with patch("pymissive.providers.brevo.provider.urlopen", side_effect=pages) as urlopen:
        events = provider._retrieve_sms_event_report("2026-01-01", "2026-01-02")
    assert len(events) == 100
    assert "offset=100" in urlopen.call_args_list[1].args[0].full_url

    error = HTTPError("https://api.brevo.com", 400, "bad", None, BytesIO(b"invalid"))
    with patch("pymissive.providers.brevo.provider.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="400: invalid"):
            provider._retrieve_sms_event_report("2026-01-01", "2026-01-02")


def test_brevo_retrieve_events_rejects_unsupported_type():
    with pytest.raises(NotImplementedError, match="whatsapp"):
        _provider(BrevoAPIProvider).retrieve_events(
            "2026-01-01",
            "2026-01-02",
            missive_type="whatsapp",
        )


def test_brevo_webhook_listing_crud_and_payload_formats():
    provider = _provider(BrevoAPIProvider, WEBHOOK_SECRET="secret")
    client = MagicMock()
    client.webhooks.get_webhooks.return_value = SimpleNamespace(
        model_dump=lambda: {
            "webhooks": [
                {"id": 1, "type": "transactional", "channel": "email"},
                SimpleNamespace(id=2, type="transactional", channel="sms", url="https://hook"),
            ]
        }
    )
    client.webhooks.create_webhook.return_value = SimpleNamespace(id=3)
    provider._get_webhooks_client = MagicMock(return_value=client)

    assert [item["id"] for item in provider.retrieve_webhooks()] == [1, 2]
    assert provider._retrieve_webhook_email("1")["id"] == 1
    assert provider._retrieve_webhook_sms("2")["id"] == 2
    assert provider.create_webhook_sms({"url": "https://hook"}) == "brevo-3"
    assert client.webhooks.create_webhook.call_args.kwargs["auth"]["token"] == "secret"
    assert provider.update_webhook_email({"id": "4", "url": "https://new"}) == "brevo-4"
    assert provider.delete_webhook_sms({"id": "4"}) == "brevo-4"
    with pytest.raises(TypeError):
        provider.update_webhook_sms({})
    with pytest.raises(TypeError):
        provider.delete_webhook_email({})
    assert provider.handle_webhook_email(b'{"event": "sent"}') == {"event": "sent"}
    assert provider.handle_webhook_sms('{"event": "sent"}') == {"event": "sent"}


def test_brevo_billings_deduplicate_valid_email_recipients():
    assert _provider(BrevoAPIProvider).get_billings_email(
        external_id="m1",
        recipients=[{"email": "a@example.com"}, {"email": "a@example.com"}, {}, "invalid"],
    ) == [
        {
            "message_id": "m1",
            "email": "a@example.com",
            "recipient": {"email": "a@example.com"},
            "billing_amount": 0.0025,
            "estimate_amount": 0.0025,
            "currency": "EUR",
            "invoice": "Email: 1",
        }
    ]


def test_scaleway_url_normalization_and_event_fallbacks():
    provider = _provider(ScalewayProvider)

    assert provider.get_subscription_id(None) is None
    assert provider.get_subscription_id("arn:topic:sub") == "sub"
    assert provider.get_normalize_webhook_id({"id": "w", "sub_id": "arn:s"}) == "scaleway-w_s"
    assert provider.get_normalize_webhook_id({"id": "w"}) == "scaleway-w"
    assert provider.get_normalize_webhook_id({}) is None
    assert provider.get_normalize_event({"Message": {"type": "email_queued"}}) == "queued"
    assert provider.get_normalize_event({"emails": [{"status": "email_delivered"}]}) == "delivered"
    assert provider.get_normalize_event({"status": "custom"}) == "unknown"
    assert provider.get_normalize_event({}) == "unknown"


def test_scaleway_prepare_email_requires_project_and_builds_optional_fields():
    with pytest.raises(ValueError, match="PROJECT_ID"):
        _provider(ScalewayProvider)._prepare_email(
            subject="Hi",
            sender_name="A",
            sender_email="a@example.com",
        )

    provider = _provider(ScalewayProvider, PROJECT_ID="p", SUFFIX_SENDER_EMAIL="mail.test")
    payload = provider._prepare_email(
        subject="Hi",
        sender_name="A",
        sender_email="a@example.com",
        body_rich="<b>Hi</b>",
        reply_to_email="reply@example.com",
        recipients=[{"email": "to@example.com"}],
        cc=[{"email": "cc@example.com"}],
        bcc=[{"email": "bcc@example.com"}],
        attachments=[{"name": "note.txt", "content": b"hello"}],
    )

    assert payload["from"]["email"] == "a@mail.test"
    assert payload["html"] == "<b>Hi</b>"
    assert payload["additional_headers"][0]["key"] == "Reply-To"
    assert payload["cc"][0]["email"] == "cc@example.com"
    assert payload["bcc"][0]["email"] == "bcc@example.com"
    assert payload["attachments"][0]["content"] == base64.b64encode(b"hello").decode()


def test_scaleway_http_webhook_and_retrieve_paths():
    provider = _provider(ScalewayProvider, PROJECT_ID="p", SECRET_ACCESS_KEY="secret")
    domains = _Response({"domains": [{"id": "d"}]})
    webhooks = _Response(
        {
            "webhooks": [
                {"id": "mine", "project_id": "p", "name": "missive-webhook-email"},
                {"id": "other", "project_id": "q", "name": "missive-webhook-email"},
            ]
        }
    )

    with patch("pymissive.providers.scaleway.requests.get", side_effect=[domains, webhooks]):
        assert provider.get_domains()["domains"][0]["id"] == "d"
        with patch.object(provider, "merge_subscriptions_url", side_effect=lambda value: value):
            assert [item["id"] for item in provider.retrieve_webhooks()] == ["mine"]

    with patch.object(provider, "retrieve_webhooks", return_value=[{"domain_id": "d", "sns_arn": "arn"}]):
        assert provider.get_or_create_webhook("d", "arn")["sns_arn"] == "arn"

    created = _Response({"id": "new"})
    with (
        patch.object(provider, "retrieve_webhooks", return_value=[]),
        patch("pymissive.providers.scaleway.requests.post", return_value=created) as post,
    ):
        assert provider.get_or_create_webhook("d", "arn") == {"id": "new"}
        assert post.call_args.kwargs["json"]["event_types"] == provider.EVENT_TYPES


def test_scaleway_retrieve_email_and_webhook_payloads():
    provider = _provider(ScalewayProvider)
    response = _Response(
        {
            "status": "email_delivered",
            "created_at": "2026-01-01T00:00:00Z",
            "email_to": "to@example.com",
        }
    )

    with patch("pymissive.providers.scaleway.requests.get", return_value=response):
        events = provider.retrieve_email(
            external_id="message",
            recipients=[{"external_id": "recipient", "email": "fallback@example.com"}],
        )
    assert events[0]["event"] == "delivered"
    assert events[0]["email"] == "to@example.com"
    assert provider.handle_webhook_email(
        json.dumps({"Type": "Notification", "Message": '{"type": "email_delivered"}'})
    )["Message"] == {"type": "email_delivered"}
    assert provider.handle_webhook_email(json.dumps({"Type": "Notification", "Message": {"type": "sent"}}))[
        "Message"
    ] == {"type": "sent"}


def test_scaleway_topics_subscriptions_and_deletion():
    provider = _provider(ScalewayProvider)
    sns = MagicMock()
    sns.get_paginator.return_value.paginate.return_value = [
        {"Topics": [{"TopicArn": "arn:other"}, {"TopicArn": "arn:missive-webhook-email"}]}
    ]
    assert provider.get_or_create_topic(sns, "missive-webhook-email") == {"TopicArn": "arn:missive-webhook-email"}

    sns.get_paginator.return_value.paginate.return_value = [{"Topics": []}]
    sns.create_topic.return_value = {"TopicArn": "arn:new"}
    assert provider.get_or_create_topic(sns, "new") == {"TopicArn": "arn:new"}

    subscriptions = [
        {"Protocol": "https", "Endpoint": "https://hook", "SubscriptionArn": "arn:sub"},
        {"Protocol": "email", "Endpoint": "ignored"},
    ]
    sns.get_paginator.return_value.paginate.return_value = [{"Subscriptions": subscriptions}]
    assert list(provider.get_subscriptions(sns, "arn:topic")) == [subscriptions[0]]
    assert provider.get_subscription(sns, "arn:topic", "https://hook") == subscriptions[0]
    assert provider.get_or_create_subscription(sns, "arn:topic", "https://hook") == subscriptions[0]
    assert provider.delete_subscription(sns, {"sns_arn": "arn:topic"}, "https://hook") == sns.unsubscribe.return_value


def test_scaleway_subscription_creation_pending_and_sns_activation():
    provider = _provider(ScalewayProvider, PROJECT_ID="p")
    sns = MagicMock()

    with patch.object(provider, "get_subscription", return_value=None):
        provider.get_or_create_subscription(sns, "arn:topic", "https://hook")
    sns.subscribe.assert_called_once()

    with patch.object(
        provider,
        "get_subscription",
        return_value={"SubscriptionArn": "pending subscription"},
    ):
        with pytest.raises(ValueError, match="Pending"):
            provider.delete_subscription(sns, {"sns_arn": "arn:topic"}, "https://hook")

    conflict = _Response({}, status_code=409)
    with (
        patch("pymissive.providers.scaleway.requests.post", return_value=conflict),
        patch.object(provider, "get_sns_info", return_value={"active": True}) as info,
    ):
        assert provider.is_sns_active() == {"active": True}
        info.assert_called_once()

    active = _Response({"active": True})
    with patch("pymissive.providers.scaleway.requests.post", return_value=active):
        assert provider.is_sns_active() == {"active": True}

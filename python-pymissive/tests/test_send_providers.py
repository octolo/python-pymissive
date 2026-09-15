"""Happy-path ``send_*`` for every shipped provider, with HTTP mocked."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import pytest

from pymissive.providers.hand_delivery import HandDeliveryProvider
from pymissive.providers.partner import PartnerProvider
from pymissive.providers.scaleway import ScalewayProvider
from pymissive.providers.slack import SlackProvider
from pymissive.providers.teams import TeamsProvider
from pymissive.providers.discord import DiscordProvider
from pymissive.utils import HTTP_DOCUMENT_TIMEOUT, HTTP_TIMEOUT


def _provider(cls, **values):
    defaults = getattr(cls, "config_defaults", {}) or {}

    class _Configured(cls):
        def _get_config_or_env(self, key, default=None):
            if key in values:
                return values[key]
            if key in defaults:
                return defaults[key]
            return default

    return _Configured()


class _UrlOpen:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_slack_send_branded_posts_chat_message():
    provider = _provider(SlackProvider, SLACK_BOT_TOKEN="xoxb-1", SLACK_CHANNEL_ID="C1")
    with patch(
        "pymissive.providers.slack.urlopen",
        return_value=_UrlOpen(b'{"ok": true, "ts": "1.2", "channel": "C1"}'),
    ) as urlopen:
        result = provider.send_branded(body_text="hello")
    request = urlopen.call_args[0][0]
    assert urlopen.call_args.kwargs["timeout"] == HTTP_TIMEOUT
    assert request.full_url == "https://slack.com/api/chat.postMessage"
    assert result["status"] == "sent"
    assert result["id"] == "1.2"


def test_slack_send_branded_raises_on_api_error():
    provider = _provider(SlackProvider, SLACK_BOT_TOKEN="x", SLACK_CHANNEL_ID="C1")
    with patch(
        "pymissive.providers.slack.urlopen",
        return_value=_UrlOpen(b'{"ok": false, "error": "invalid_auth"}'),
    ):
        with pytest.raises(RuntimeError, match="invalid_auth"):
            provider.send_branded(subject="x")


def test_teams_send_branded_posts_webhook():
    provider = _provider(TeamsProvider, TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/x")
    with patch(
        "pymissive.providers.teams.urlopen",
        return_value=_UrlOpen(b"1"),
    ) as urlopen:
        result = provider.send_branded(body_text="hello")
    assert urlopen.call_args[0][0].full_url.endswith("/webhook/x")
    assert urlopen.call_args.kwargs["timeout"] == HTTP_TIMEOUT
    assert result["status"] == "sent"


def test_teams_send_branded_raises_on_http_error():
    provider = _provider(TeamsProvider, TEAMS_WEBHOOK_URL="https://outlook.office.com/webhook/x")
    error = HTTPError(
        "https://outlook.office.com/webhook/x", 400, "Bad", hdrs=None, fp=BytesIO(b"no")
    )
    with patch("pymissive.providers.teams.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="400"):
            provider.send_branded(body_text="hello")


def test_discord_validates_before_importing_the_sdk():
    provider = _provider(DiscordProvider)
    with pytest.raises(ValueError, match="channel_id"):
        provider.send_branded(body_text="hello")
    provider = _provider(DiscordProvider, DISCORD_CHANNEL_ID="1")
    with pytest.raises(ValueError, match="content"):
        provider.send_branded()


def test_partner_request_sets_a_timeout():
    provider = _provider(PartnerProvider, SMS_API_KEY="k")
    response = Mock()
    response.json.return_value = {"ok": True}
    with patch("pymissive.providers.partner.requests.request", return_value=response) as request:
        provider._request("https://api.smspartner.fr/v1/send", "POST", {"apiKey": "k"})
    assert request.call_args.kwargs["timeout"] == HTTP_TIMEOUT


def test_partner_send_sms_posts_to_smspartner():
    provider = _provider(PartnerProvider, SMS_API_KEY="k")
    with patch.object(
        provider, "_request", return_value={"success": True, "messageId": "m1"}
    ) as request:
        result = provider.send_sms(
            body_text="hi",
            recipients=[{"phone": "+33600000000"}],
        )
    assert request.call_args[0][0].endswith("/send")
    assert request.call_args[0][1] == "POST"
    assert result["messageId"] == "m1"


def test_partner_send_sms_respects_disable_send(monkeypatch):
    monkeypatch.setenv("PYMISSIVE_DISABLE_SEND", "1")
    provider = _provider(PartnerProvider, SMS_API_KEY="k")
    with patch.object(provider, "_request") as request:
        result = provider.send_sms(body_text="hi", recipients=[{"phone": "+336"}])
    request.assert_not_called()
    assert result["disabled_send"] is True


def test_scaleway_send_email_posts_transactional_payload():
    provider = _provider(
        ScalewayProvider,
        PROJECT_ID="proj",
        ACCESS_KEY="ak",
        SECRET_ACCESS_KEY="sk",
        SUFFIX_SENDER_EMAIL="mail.example",
    )
    response = Mock()
    response.json.return_value = {"id": "scw-1"}
    response.raise_for_status = Mock()
    with patch("pymissive.providers.scaleway.requests.post", return_value=response) as post:
        result = provider.send_email(
            subject="Hello",
            sender_name="Bot",
            sender_email="bot@example.com",
            body_text="hi",
            recipients=[{"email": "a@b.c"}],
        )
    assert post.call_args.kwargs["json"]["project_id"] == "proj"
    assert post.call_args.kwargs["timeout"] == HTTP_DOCUMENT_TIMEOUT
    assert result["event"] == "sent"
    assert result["external_id"] == "scw-1"


def test_hand_delivery_send_needs_no_network():
    result = HandDeliveryProvider().send_hand_delivery(
        sender={"name": "Octolo", "address": {"address_line1": "23 rue des Champignons"}},
        recipients=[{"id": "rec-1", "name": "Charles"}],
    )
    assert result["event"] == "delivered"
    assert result["external_id"] == "octolo-23ruedeschampignons"
    assert result["recipients"][0]["external_id"].endswith("charles")

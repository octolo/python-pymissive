"""Brevo tags: list on send, filter on retrieve, list on normalize."""

import json
import sys
import types
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from pymissive.providers.brevo import BrevoAPIProvider


def _provider():
    provider = BrevoAPIProvider()
    provider._email_api_key = "email-key"
    provider._sms_api_key = "sms-key"
    return provider


def test_tags_accepts_list_string_and_webhook_json():
    provider = _provider()
    assert provider._tags([" welcome ", "", "invoice", "welcome"]) == ["welcome", "invoice"]
    assert provider._tags("invoice") == ["invoice"]
    assert provider._tags('["welcome", "invoice"]') == ["welcome", "invoice"]
    assert provider._tags(None) == []
    assert provider._tags(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"]) == [
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
    ]


def test_normalize_tags_from_event_tag():
    provider = _provider()
    assert provider.get_normalize_tags({"tag": "invoice"}) == ["invoice"]
    assert provider.get_normalize_tags({"tags": ["welcome"]}) == ["welcome"]
    assert provider.get_normalize_tags({"message_id": "m1"}) is None


class _Body:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def brevo_email_sdk(monkeypatch):
    """send_email imports the SDK lazily. Stub it when the extra is absent."""
    emails = types.ModuleType("brevo.transactional_emails")

    class _Item:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    for name in (
        "SendTransacEmailRequestBccItem",
        "SendTransacEmailRequestCcItem",
        "SendTransacEmailRequestReplyTo",
        "SendTransacEmailRequestSender",
        "SendTransacEmailRequestToItem",
    ):
        setattr(emails, name, type(name, (_Item,), {}))
    monkeypatch.setitem(sys.modules, "brevo", types.ModuleType("brevo"))
    monkeypatch.setitem(sys.modules, "brevo.transactional_emails", emails)


def test_send_email_forwards_tags(monkeypatch, brevo_email_sdk):
    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)
    provider = _provider()
    client = MagicMock()
    response = MagicMock()
    response.model_dump.return_value = {"message_id": "m1"}
    client.transactional_emails.send_transac_email.return_value = response
    provider._get_email_client = MagicMock(return_value=client)
    provider.delete_blocked_emails = MagicMock()

    provider.send_email(
        subject="Hi",
        sender={"email": "a@b.c", "name": "A"},
        recipients=[{"email": "c@d.e"}],
        body_text="hello",
        tags=["welcome", "invoice"],
    )

    sent = client.transactional_emails.send_transac_email.call_args.kwargs
    assert sent["tags"] == ["welcome", "invoice"]


def test_send_email_omits_empty_tags(monkeypatch, brevo_email_sdk):
    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)
    provider = _provider()
    client = MagicMock()
    response = MagicMock()
    response.model_dump.return_value = {"message_id": "m1"}
    client.transactional_emails.send_transac_email.return_value = response
    provider._get_email_client = MagicMock(return_value=client)
    provider.delete_blocked_emails = MagicMock()

    provider.send_email(
        subject="Hi",
        sender={"email": "a@b.c"},
        recipients=[{"email": "c@d.e"}],
        body_text="hello",
    )

    assert "tags" not in client.transactional_emails.send_transac_email.call_args.kwargs


def test_send_sms_posts_tag_list(monkeypatch):
    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)
    provider = _provider()
    captured = {}

    def urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return _Body(b'{"messageId": "sms-1"}')

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = provider.send_sms(
        sender={"name": "Shop"},
        recipients=[{"phone": "+33600000000"}],
        body_text="hello",
        tags=["invoice"],
    )

    assert captured["body"]["tag"] == ["invoice"]
    assert result["messageId"] == "sms-1"


def test_retrieve_events_email_filters_by_tags():
    provider = _provider()
    client = MagicMock()
    client.transactional_emails.get_email_event_report.return_value = SimpleNamespace(events=[])
    provider._get_email_client = MagicMock(return_value=client)

    provider.retrieve_events(
        date(2026, 8, 20), date(2026, 8, 20), missive_type="email", tags=["invoice"]
    )

    sent = client.transactional_emails.get_email_event_report.call_args.kwargs
    assert sent["tags"] == '["invoice"]'


def test_retrieve_events_sms_filters_by_tags(monkeypatch):
    provider = _provider()
    captured = {}

    def urlopen(req, timeout):
        captured["query"] = parse_qs(urlparse(req.full_url).query)
        return _Body(b'{"events": []}')

    monkeypatch.setattr("pymissive.providers.brevo.urlopen", urlopen)
    provider.retrieve_events(
        date(2026, 8, 20), date(2026, 8, 20), missive_type="sms", tags=["invoice"]
    )

    assert captured["query"]["tags"] == ['["invoice"]']


def test_send_email_sdk_body_contains_tags(monkeypatch):
    """brevo-python must put tags on POST /smtp/email, not only on the method kwargs."""
    pytest.importorskip("brevo")
    from brevo.core.http_client import get_request_body

    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)
    provider = _provider()
    provider.delete_blocked_emails = MagicMock()
    captured = {}

    def fake_request(self, path=None, *, method, json=None, omit=None, request_options=None, **kwargs):
        body, _data = get_request_body(
            json=json, data=None, request_options=request_options, omit=omit
        )
        captured["path"] = path
        captured["body"] = body

        class _Response:
            status_code = 201
            headers = {}
            text = ""

            def json(self):
                return {"messageId": "<m1@brevo>"}

        return _Response()

    monkeypatch.setattr("brevo.core.http_client.HttpClient.request", fake_request)
    provider.send_email(
        subject="Hi",
        sender={"email": "a@b.c", "name": "A"},
        recipients=[{"email": "c@d.e", "name": "C"}],
        body_text="hello",
        tags=["welcome", "invoice"],
    )

    assert captured["path"] == "smtp/email"
    assert captured["body"]["tags"] == ["welcome", "invoice"]

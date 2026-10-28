"""FakeProvider accepts every send service and sleeps for the configured duration."""

import json
from unittest.mock import patch

import pytest

from pymissive.config import MISSIVE_TYPES
from pymissive.providers.fake import FakeProvider


@pytest.fixture(autouse=True)
def allow_fake_provider(monkeypatch):
    monkeypatch.setenv("PYMISSIVE_ALLOW_FAKE_PROVIDER", "1")
    monkeypatch.delenv("PYMISSIVE_DISABLE_SEND", raising=False)


def test_every_missive_type_has_a_send_service():
    provider = FakeProvider()
    missing = [
        missive_type
        for missive_type in MISSIVE_TYPES
        if not provider.is_service_implemented(f"send_{missive_type}")
        or not provider.is_service_implemented(f"handle_webhook_{missive_type}")
    ]
    assert missing == []


def test_handle_webhook_normalizes_a_json_body():
    provider = FakeProvider()
    body = json.dumps(
        [
            {
                "external_id": "fake-email-1",
                "event": "delivered",
                "occurred_at": "2026-10-21T12:00:00+00:00",
                "recipient": {"id": 3},
                "reason": "Fake webhook (delivered)",
            }
        ]
    ).encode()
    normalized = provider.call_service_formatted("handle_webhook_email", payload=body)
    assert normalized[0]["event"] == "delivered"
    assert normalized[0]["external_id"] == "fake-email-1"
    assert normalized[0]["recipient"] == {"id": 3}
    assert normalized[0]["raw"]["event"] == "delivered"


def test_send_returns_an_external_id():
    provider = FakeProvider(config={"SLEEP_SECONDS": 0})
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        result = provider.send_email(internal_id="m-1")
    sleep.assert_not_called()
    assert result["external_id"].startswith("fake-email-")
    assert result["event"] == "sent"
    assert result["code"] == 200


def test_send_ignores_missive_type_echoed_by_the_payload():
    provider = FakeProvider(config={"SLEEP_SECONDS": 0})
    result = provider.send_email(missive_type="email", internal_id="m-1")
    assert result["external_id"].startswith("fake-email-")
    assert result["service"] == "send_email"


def test_a_send_lasts_ten_seconds_by_default():
    provider = FakeProvider()
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        provider.send_email()
    sleep.assert_called_once_with(10)


def test_sleep_seconds_on_the_call_is_the_send_duration():
    provider = FakeProvider(config={"SLEEP_SECONDS": 30})
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        provider.send_sms(sleep_seconds=2)
    sleep.assert_called_once_with(2)


def test_provider_config_is_the_duration_when_the_call_omits_it():
    provider = FakeProvider(config={"SLEEP_SECONDS": "1.5"})
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        provider.send_letter()
    sleep.assert_called_once_with(1.5)


def test_zero_and_invalid_durations_do_not_sleep():
    provider = FakeProvider(config={"SLEEP_SECONDS": "nope"})
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        provider.send_sms(sleep_seconds=0)
        provider.send_sms(sleep_seconds=-3)
        provider.send_email()
    sleep.assert_not_called()


def test_force_fake_provider_allows_the_send(monkeypatch):
    monkeypatch.delenv("PYMISSIVE_ALLOW_FAKE_PROVIDER")
    monkeypatch.setenv("PYMISSIVE_FORCE_FAKE_PROVIDER", "1")
    provider = FakeProvider(config={"SLEEP_SECONDS": 0})
    result = provider.send_sms()
    assert result["external_id"].startswith("fake-sms-")


def test_send_is_refused_unless_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("PYMISSIVE_ALLOW_FAKE_PROVIDER")
    monkeypatch.delenv("PYMISSIVE_FORCE_FAKE_PROVIDER", raising=False)
    provider = FakeProvider()
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        with pytest.raises(RuntimeError, match="PYMISSIVE_ALLOW_FAKE_PROVIDER"):
            provider.send_email()
    sleep.assert_not_called()


def test_disabled_send_returns_at_once(monkeypatch):
    monkeypatch.setenv("PYMISSIVE_DISABLE_SEND", "1")
    provider = FakeProvider()
    with patch("pymissive.providers.fake.time.sleep") as sleep:
        result = provider.send_email()
    sleep.assert_not_called()
    assert result["disabled_send"] is True

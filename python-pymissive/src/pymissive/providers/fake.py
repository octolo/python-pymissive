"""Local provider that accepts every send without calling a network.

Each ``send_*`` blocks for a configurable duration, to simulate shorter or
longer sends (watching a campaign run, cancelling it by hand). The duration
is read in this order:

- ``sleep_seconds`` on the call (a missive's ``additional_config`` is forwarded)
- ``SLEEP_SECONDS`` on this provider (``PROVIDERKIT_PROVIDERS_CONFIG["fake"]``)
- ``10``

Sends are refused unless ``PYMISSIVE_ALLOW_FAKE_PROVIDER`` is true, so a
misconfigured production never marks missives as sent without sending them.

``handle_webhook_*`` reads a JSON body already shaped like a normalized event
(``external_id``, ``event``, ``occurred_at``, ``recipient``, ``reason``).
django-pymissive posts those bodies to ``/webhook/fake/<missive_type>/``.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pymissive.config import ALL_EVENTS, MISSIVE_TYPES
from pymissive.utils import is_disable_send, is_fake_provider_allowed

from .base import MissiveProviderBase

logger = logging.getLogger(__name__)

DEFAULT_SLEEP_SECONDS = 10


class FakeProvider(MissiveProviderBase):
    """Stand-in provider: every missive type sends locally."""

    name = "fake"
    display_name = "Fake"
    description = "Local provider for every send service. No network call."
    required_packages: list[str] = []
    config_keys = ["SLEEP_SECONDS"]
    config_defaults: dict[str, Any] = {"SLEEP_SECONDS": DEFAULT_SLEEP_SECONDS}

    def _sleep_seconds(self, kwargs: dict[str, Any]) -> float:
        raw = kwargs.get("sleep_seconds")
        if raw is None:
            raw = self._get_config_or_env("SLEEP_SECONDS", DEFAULT_SLEEP_SECONDS)
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            return 0
        return seconds if seconds > 0 else 0

    def _send(self, missive_type: str, **kwargs: Any) -> dict[str, Any]:
        if not is_fake_provider_allowed():
            raise RuntimeError("Fake provider is disabled: set PYMISSIVE_ALLOW_FAKE_PROVIDER to use it.")
        external_id = kwargs.get("external_id") or f"fake-{missive_type}-{uuid.uuid4()}"
        if is_disable_send():
            return self._disabled_send_response(f"send_{missive_type}", external_id=external_id)
        seconds = self._sleep_seconds(kwargs)
        if seconds:
            logger.info("fake send_%s %ss", missive_type, seconds)
            time.sleep(seconds)
        return {
            "id": external_id,
            "external_id": external_id,
            "event": "sent",
            "code": 200,
            "message": "Fake send",
            "event_date": datetime.now(timezone.utc).isoformat(),
            "service": f"send_{missive_type}",
        }

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        event = data.get("event") if isinstance(data, dict) else None
        if event in ALL_EVENTS:
            return str(event)
        return "unknown"

    @staticmethod
    def _read_webhook(payload: Any) -> Any:
        """Decode the raw webhook body. A dict or list is already parsed."""
        if isinstance(payload, (bytes, bytearray)):
            text = payload.decode("utf-8").strip()
            if not text:
                return []
            return json.loads(text)
        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return []
            return json.loads(text)
        if payload is None:
            return []
        return payload


def _send_method(missive_type: str):
    def send(self, **kwargs: Any) -> dict[str, Any]:
        # The missive payload echoes its own type. The method already received
        # it as the service name (``send_email``), so the key must not be
        # forwarded again.
        kwargs.pop("missive_type", None)
        return self._send(missive_type, **kwargs)

    send.__name__ = f"send_{missive_type}"
    send.__qualname__ = f"FakeProvider.send_{missive_type}"
    send.__doc__ = f"Accept a {missive_type} send locally."
    return send


def _webhook_method(missive_type: str):
    def handle_webhook(self, payload: Any = None, **kwargs: Any) -> Any:
        return FakeProvider._read_webhook(payload)

    handle_webhook.__name__ = f"handle_webhook_{missive_type}"
    handle_webhook.__qualname__ = f"FakeProvider.handle_webhook_{missive_type}"
    handle_webhook.__doc__ = f"Normalize a {missive_type} webhook body."
    return handle_webhook


for _missive_type in MISSIVE_TYPES:
    setattr(FakeProvider, f"send_{_missive_type}", _send_method(_missive_type))
    setattr(
        FakeProvider,
        f"handle_webhook_{_missive_type}",
        _webhook_method(_missive_type),
    )

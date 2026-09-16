from datetime import datetime, timezone as dt_timezone

from providerkit import ProviderBase
import base64
import mimetypes
from typing import Any
from .acknowledgement import AcknowledgementMixin
from .attachments import AttachmentsMixin
from .branded import BrandedMixin
import re
import unicodedata
from pymissive import config

defaults_services = {
    "retrieve_webhooks": {
        "fields": config.WEBHOOK_FIELDS,
    },
}


for category, service_cfg in config.MISSIVE_SERVICES.items():
    for service in service_cfg["services"].items():
        for missive_type in config.MISSIVE_TYPES.keys():
            defaults_services[f"{service[0]}_{missive_type}"] = {
                "description": service[1],
                "fields": service_cfg["config"]
            }


class MissiveProviderBase(
    ProviderBase,
    AcknowledgementMixin,
    AttachmentsMixin,
    BrandedMixin,
):
    """Base class for Missive providers."""
    _default_services_cfg = defaults_services
    provider_key = "key"
    events_association = None
    fields_associations: dict = {}

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self.attachments: list[Any] = []

    def get_webhook_secret(self) -> str:
        """Return ``WEBHOOK_SECRET`` or empty when inbound auth is off."""
        from pymissive.webhook_auth import get_webhook_secret

        return get_webhook_secret(self)

    def webhook_uses_url_token(self) -> bool:
        """True when the provider cannot send an Authorization header (SNS)."""
        return False

    def verify_inbound_webhook(
        self, *, authorization: str = "", url_token: str = ""
    ) -> bool:
        """Opt-in inbound check. See ``pymissive.webhook_auth``."""
        from pymissive.webhook_auth import verify_inbound_webhook

        return verify_inbound_webhook(
            self, authorization=authorization, url_token=url_token
        )

    def _to_base64(self, content):
        if isinstance(content, bytes):
            return base64.b64encode(content).decode("ascii")
        return content

    def _guess_content_type(self, name: str) -> str:
        """Guess MIME type from filename. Scaleway requires a type from its allowed list."""
        guessed, _ = mimetypes.guess_type(name)
        return guessed or "application/octet-stream"

    def get_events_association(self) -> dict[str, str]:
        """Return mapping of provider events to missive event."""
        return self.events_association or {}

    def retrieve_events(self, start_date: datetime | str, end_date: datetime | str, **kwargs: Any) -> list:
        """Retrieve events in bulk between ``start_date`` and ``end_date``.

        Typed services (``retrieve_events_email``, ``retrieve_events_sms``, …)
        delegate here. Named ``retrieve_events`` so it does not collide with the
        response field ``events`` during providerkit normalization.

        Providers override this method; it is not implemented on current providers.

        Args:
            start_date: Inclusive start of the period.
            end_date: Inclusive end of the period.

        Returns:
            A list of normalized events.

        Raises:
            NotImplementedError: Always, until a provider implements it.
        """
        raise NotImplementedError("retrieve_events is not implemented")

    def retrieve_billings(self, start_date: datetime | str, end_date: datetime | str, **kwargs: Any) -> list:
        """Retrieve billings in bulk between ``start_date`` and ``end_date``.

        Typed services (``retrieve_billings_registered_letter``, ``retrieve_billings_email``, …)
        delegate here. Named ``retrieve_billings`` so it does not collide with
        ``get_billings`` (per-missive) during providerkit service dispatch.

        Args:
            start_date: Inclusive start of the period.
            end_date: Inclusive end of the period.

        Returns:
            A list of normalized billing records.

        Raises:
            NotImplementedError: Always, until a provider implements it.
        """
        raise NotImplementedError("retrieve_billings is not implemented")

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Return the normalized event of webhook/email/SMS."""
        return (self.events_association or {}).get(data.get("event"), "unknown")

    def get_normalize_webhook_id(self, data: dict) -> str:
        cfg = config.WEBHOOK_FIELDS.get("webhook_id")
        source = cfg.get("source", self.fields_associations.get("webhook_id", "webhook_id"))
        webhook_id = self._normalize_recursive(data, "webhook_id", source)
        if webhook_id:
            return f"{self.name}-{webhook_id}"
        return None

    def normalize_filename(self, name):
        name = unicodedata.normalize("NFKD", name)
        name = re.sub(r"\s+", "_", name)      # spaces -> _
        name = re.sub(r"[^\w\.-]", "", name)  # strip special characters
        return name

    def _disabled_send_response(self, service_name: str, **extra: Any) -> dict[str, Any]:
        """Response returned by a ``send_*`` service when sending is disabled.

        Providers call this at the very end of their ``send_*`` method, after
        every preparation/staging step, *instead* of the final confirmation
        network call (``PYMISSIVE_DISABLE_SEND``). ``extra`` lets a provider
        carry data already produced upstream (``external_id``, ``recipients``,
        ``attachments``, ...).
        """
        external_id = extra.get("external_id") or extra.get("id")
        response = {
            "external_id": external_id,
            "id": external_id,
            "event": "disabled",
            "code": 200,
            "message": "Send disabled (PYMISSIVE_DISABLE_SEND)",
            "disabled_send": True,
            "event_date": datetime.now(dt_timezone.utc).isoformat(),
            "service": service_name,
        }
        response.update(extra)
        return response


def _retrieve_events_for_type(missive_type: str):
    def retrieve_events_type(self, start_date: datetime | str, end_date: datetime | str, **kwargs: Any) -> list:
        return self.retrieve_events(start_date, end_date, missive_type=missive_type, **kwargs)

    retrieve_events_type.__name__ = f"retrieve_events_{missive_type}"
    retrieve_events_type.__qualname__ = f"MissiveProviderBase.retrieve_events_{missive_type}"
    retrieve_events_type.__doc__ = f"Retrieve {missive_type} events between start_date and end_date."
    return retrieve_events_type


def _retrieve_billings_for_type(missive_type: str):
    def retrieve_billings_type(self, start_date: datetime | str, end_date: datetime | str, **kwargs: Any) -> list:
        return self.retrieve_billings(start_date, end_date, missive_type=missive_type, **kwargs)

    retrieve_billings_type.__name__ = f"retrieve_billings_{missive_type}"
    retrieve_billings_type.__qualname__ = f"MissiveProviderBase.retrieve_billings_{missive_type}"
    retrieve_billings_type.__doc__ = f"Retrieve {missive_type} billings between start_date and end_date."
    return retrieve_billings_type


for _missive_type in config.MISSIVE_TYPES:
    setattr(
        MissiveProviderBase,
        f"retrieve_events_{_missive_type}",
        _retrieve_events_for_type(_missive_type),
    )
    setattr(
        MissiveProviderBase,
        f"retrieve_billings_{_missive_type}",
        _retrieve_billings_for_type(_missive_type),
    )
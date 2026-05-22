"""Hand delivery provider — no external API, records manual hand-over.

This provider tracks missives that are physically handed to the recipient
(``remise en main propre``). It does not call any third-party API and does
not require extra packages: it only allocates a deterministic, human
readable ``external_id`` and emits the local events expected by ``Missive``
so the standard pipeline (status, events, attachments) keeps working.

The missive type is ``hand_delivery`` (declared in
``pymissive.config.address``). Proof of delivery (signed receipt, photo, …)
is expected to be stored as a regular ``MissiveAttachment`` with type
``PROOF``.
"""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .base import MissiveProviderBase


class HandDeliveryProvider(MissiveProviderBase):
    """In-person hand delivery provider (no external API)."""

    name = "hand_delivery"
    display_name = "Hand delivery"
    description = "In-person hand delivery (no external API, no library)."
    required_packages: list[str] = []
    config_keys = ["DELIVERER_NAME"]
    config_defaults: dict[str, Any] = {}

    events_association = {
        "request": "request",
        "delivered": "delivered",
        "refused": "refused",
        "attempted": "attempted_delivery",
        "cancelled": "cancelled",
    }

    fields_associations = {
        "external_id": ("external_id", "id"),
        "internal_id": "internal_id",
        "occurred_at": ("event_date", "occurred_at"),
        "event": "event",
        "recipient": "recipient",
    }

    #########################################################
    # Helpers
    #########################################################

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=timezone.utc)

    @classmethod
    def _now_iso(cls) -> str:
        return cls._now().isoformat()

    @staticmethod
    def _slug_part(value: Any) -> str:
        """Strip accents/spaces/special chars and lowercase.

        ``"23 rue des Champignons"`` -> ``"23ruedeschampignons"``.
        """
        if not value:
            return ""
        text = unicodedata.normalize("NFKD", str(value))
        text = "".join(c for c in text if not unicodedata.combining(c))
        return re.sub(r"[^A-Za-z0-9]", "", text).lower()

    @classmethod
    def _address_slug(cls, address: dict[str, Any] | None) -> str:
        """Slug of the first non-empty address line we can find."""
        if not address:
            return ""
        for key in ("address_line1", "address_line_4", "address_line2", "street"):
            if address.get(key):
                return cls._slug_part(address[key])
        return ""

    @classmethod
    def _build_missive_external_id(cls, sender: dict[str, Any] | None) -> str:
        """``octolo-23ruedeschampignons`` (sender name + sender address)."""
        sender = sender or {}
        parts = [
            cls._slug_part(sender.get("name")),
            cls._address_slug(sender.get("address")),
        ]
        return "-".join(p for p in parts if p) or "hand-delivery"

    @classmethod
    def _build_recipient_external_id(
        cls,
        sender: dict[str, Any] | None,
        recipient: dict[str, Any] | None,
    ) -> str:
        """``octolo-23ruedeschampignons-charleshubert`` (missive id + recipient name)."""
        recipient = recipient or {}
        missive_id = cls._build_missive_external_id(sender)
        recipient_part = cls._slug_part(recipient.get("name"))
        if recipient_part:
            return f"{missive_id}-{recipient_part}"
        return missive_id

    def _serialize_recipients(
        self,
        recipients: list[dict[str, Any]] | None,
        sender: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "internal_id": recipient.get("id"),
                "external_id": (
                    recipient.get("external_id")
                    or self._build_recipient_external_id(sender, recipient)
                ),
            }
            for recipient in (recipients or [])
        ]

    def _serialize_attachments(
        self, attachments: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        return [
            {
                "internal_id": attachment.get("id"),
                "external_id": attachment.get("external_id") or str(attachment.get("id")),
            }
            for attachment in (attachments or [])
        ]

    def _build_per_recipient_events(
        self,
        event: str,
        recipients_in: list[dict[str, Any]] | None,
        recipients_out: list[dict[str, Any]],
        missive_external_id: str,
        when: datetime,
    ) -> list[dict[str, Any]]:
        """One event per recipient, looked up by ``id`` (== ``MissiveRecipient.id``)."""
        events: list[dict[str, Any]] = []
        for rec_in, rec_out in zip(recipients_in or [], recipients_out):
            rec_id = rec_in.get("id")
            if not rec_id:
                continue
            events.append({
                "external_id": missive_external_id,
                "event": event,
                "event_date": when.isoformat(),
                "recipient": {"id": rec_id},
            })
        return events

    def _resolve_missive_external_id(
        self,
        kwargs: dict[str, Any],
        sender: dict[str, Any] | None,
    ) -> str:
        """Re-use an existing external_id; else build from sender."""
        if kwargs.get("external_id"):
            return kwargs["external_id"]
        return self._build_missive_external_id(sender)

    def _base_response(self, event: str, **kwargs: Any) -> dict[str, Any]:
        when = self._now()
        sender = kwargs.get("sender")
        recipients_in = kwargs.get("recipients") or []
        recipients_out = self._serialize_recipients(recipients_in, sender)
        attachments_out = self._serialize_attachments(kwargs.get("attachments"))
        external_id = self._resolve_missive_external_id(kwargs, sender)
        return {
            "id": external_id,
            "external_id": external_id,
            "event": event,
            "event_date": when.isoformat(),
            "code": 200,
            "message": event,
            "recipients": recipients_out,
            "attachments": attachments_out,
            "events": self._build_per_recipient_events(
                event, recipients_in, recipients_out, external_id, when,
            ),
        }

    #########################################################
    # hand_delivery - lifecycle (no external API)
    #########################################################

    def create_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        """Allocate a deterministic external_id and return a draft response."""
        return self._base_response("request", **kwargs)

    def prepare_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        return self.create_hand_delivery(**kwargs)

    def update_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        return self._base_response("request", **kwargs)

    def send_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        """Mark the missive as handed over to the recipient(s)."""
        response = self._base_response("delivered", **kwargs)
        response["message"] = "Hand delivered"
        return response

    def cancel_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        response = self._base_response("cancelled", **kwargs)
        response["message"] = "cancelled"
        return response

    def delete_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        response = self._base_response("cancelled", **kwargs)
        response["message"] = "deleted"
        return response

    def retrieve_hand_delivery(self, **kwargs: Any) -> dict[str, Any]:
        """No remote state to fetch; expose what the caller already has."""
        external_id = kwargs.get("external_id")
        return {
            "id": external_id,
            "external_id": external_id,
            "events": [],
        }

    def handle_webhook_hand_delivery(self, payload: Any) -> Any:
        """Pass-through: events emitted by ``send_hand_delivery`` are already normalized."""
        return payload

    #########################################################
    # Normalization
    #########################################################

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        return self.events_association.get(data.get("event"), "unknown")

    def get_normalize_occurred_at(self, data: dict[str, Any]) -> str:
        return data.get("event_date") or data.get("occurred_at") or self._now_iso()

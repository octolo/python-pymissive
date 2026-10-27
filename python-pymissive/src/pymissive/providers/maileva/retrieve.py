import json
from typing import Any, cast

from pymissive.utils import HTTP_DOCUMENT_TIMEOUT
from .helpers import (
    _address_from_maileva_lines,
    _billing_page_is_last,
    _billing_page_items,
    _billing_page_params,
    _existing_recipient_ref,
    _is_recipient_resource,
    _provider_custom_id,
    extract_tracking_number_from_deposit_proof,
)
from .types import MailevaMixinTypingBase


class MailevaRetrieveMixin(MailevaMixinTypingBase):
    def get_normalize_events(self, data):
        if "events" in data:
            return data.get("events")
        return None

    def get_normalize_sender_name(self, data: dict[str, Any]) -> str | None:
        name = (data.get("sender_name") or data.get("sender_address_line_2") or "").strip()
        return name or None

    def get_normalize_sender_address(self, data: dict[str, Any]) -> dict[str, str] | None:
        existing = data.get("sender_address")
        if isinstance(existing, dict) and any(
            existing.get(key) for key in ("address_line1", "city", "organization", "postal_code")
        ):
            return existing
        return _address_from_maileva_lines(data, prefix="sender_", country_key="sender_country_code")

    def get_normalize_recipients(self, data: dict[str, Any]) -> list | None:
        recipients = data.get("recipients")
        if not isinstance(recipients, list):
            return None
        return [
            self._serialize_recipient_ref(
                {
                    "id": rec.get("internal_id") or rec.get("custom_id") or rec.get("id"),
                    "name": rec.get("name"),
                    "address": rec.get("address") if isinstance(rec.get("address"), dict) else None,
                },
                rec,
            )
            if isinstance(rec, dict)
            else rec
            for rec in recipients
        ]

    def _recipient_event_ref(self, recipient: dict[str, Any]) -> dict[str, Any]:
        """Keys Django ``get_recipient`` can match on a retrieved sending.

        Missive identity is the sending ``resource_id``. Do not put Maileva's
        recipient UUID in ``external_id``: that value is not the missive id
        and would steal event-level ``external_id`` if copied upward.
        """
        ref: dict[str, Any] = {}
        if recipient.get("custom_id"):
            ref["id"] = recipient["custom_id"]
            ref["substitute_id"] = recipient["custom_id"]
        name = (recipient.get("address_line_2") or recipient.get("name") or "").strip()
        if name:
            ref["name"] = name
        return ref

    def _serialize_events_postal(self, recipients, detail_registered_letter):
        events = []
        for recipient in recipients:
            recipient_ref = self._recipient_event_ref(recipient)
            if "statuses" in recipient:
                for status in recipient.get("statuses", []):
                    events.append(
                        {
                            "resource_id": detail_registered_letter.get("id"),
                            "event": status.get("code"),
                            "event_date": status.get("date"),
                            "recipient": recipient_ref,
                        }
                    )
            elif "status" in recipient:
                events.append(
                    {
                        "recipient": recipient_ref,
                        "resource_id": detail_registered_letter.get("id"),
                        "event": recipient.get("status"),
                        "event_date": detail_registered_letter.get("submission_date"),
                    }
                )
        return events

    def _retrieve_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        external_id = cast(str, kwargs.get("external_id"))
        detail = self._detail_sending_postal(external_id, product=product)
        recipients = self._detail_recipients_postal(external_id, product=product)
        result = {
            **detail,
            "events": self._serialize_events_postal(recipients, detail),
            "recipients": [
                self._serialize_recipient_ref({"id": recipient.get("custom_id")}, recipient) for recipient in recipients
            ],
        }
        if not result.get("subject") and detail.get("name"):
            result["subject"] = detail["name"]
        sender_name = (detail.get("sender_address_line_2") or "").strip()
        if sender_name and not result.get("sender_name"):
            result["sender_name"] = sender_name
        sender_address = _address_from_maileva_lines(detail, prefix="sender_", country_key="sender_country_code")
        if sender_address:
            result["sender_address"] = sender_address
        return result

    def retrieve_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._retrieve_postal(product="letter", **kwargs)

    def retrieve_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._retrieve_postal(product="registered_letter", **kwargs)

    def _tracking_number_postal(self, *, product: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Return carrier tracking numbers for each recipient of a sending.

        Maileva prints the public tracking reference on the deposit-proof PDF
        (domestic: number under ``Numéro de la LR``; international: UPU S10
        under ``NUMERO DE RECOMMANDE``). The recipient API fields are only a
        fallback when no proof is available yet.
        """
        external_id = cast(str, kwargs.get("external_id"))
        recipients = self._detail_recipients_postal(external_id, product=product)
        results = []
        for recipient in recipients:
            ref = self._serialize_recipient_ref({"id": recipient.get("custom_id")}, recipient)
            # LR / recommandé numbers are printed on the deposit-proof PDF.
            # mail/v3 exposes ``tracking_number`` on the recipient (TRACKED_LETTER).
            if product == "registered_letter":
                proof_url = recipient.get("deposit_proof_url")
                if proof_url:
                    try:
                        pdf_bytes = self._download_proof_bytes(proof_url, product=product)
                        tracking_number = extract_tracking_number_from_deposit_proof(pdf_bytes)
                    except Exception:
                        tracking_number = None
                    if tracking_number:
                        ref["tracking_number"] = tracking_number
            results.append(ref)
        return results

    def tracking_number_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._tracking_number_postal(product="letter", **kwargs)

    def tracking_number_registered_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._tracking_number_postal(product="registered_letter", **kwargs)

    #########################################################
    # registered letter / letter - Billings
    #########################################################

    @staticmethod
    def _as_billing_date(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()[:10]
        return str(value)[:10]

    def _recipient_item_pages(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Paginate ``GET /billing/v1/recipient_items`` (start_index / count)."""
        url = self.get_endpoint("invoice")
        items: list[dict[str, Any]] = []
        start_index = 1
        count = 100
        while True:
            page_params = _billing_page_params(params, start_index, count)
            response = self._request("GET", url, params=page_params)
            self._raise_for_response(response, f"Maileva billing failed ({url})")
            data = response.json()
            page = _billing_page_items(data)
            items.extend(page)
            if _billing_page_is_last(data, page, len(items), count):
                break
            start_index += count
        return items

    def _serialize_billing_item(self, item: dict[str, Any], *, external_id: Any = None) -> dict[str, Any]:
        user_reference = item.get("user_reference")
        sending_id = item.get("sending_id") or external_id
        recipient_id = item.get("recipient_id")
        recipient_custom_id = item.get("recipient_custom_id")
        recipient = None
        if recipient_id or recipient_custom_id:
            recipient = {}
            if recipient_custom_id:
                recipient["id"] = recipient_custom_id
                recipient["substitute_id"] = recipient_custom_id
            if recipient_id:
                recipient["external_id"] = recipient_id
                recipient.setdefault("id", recipient_id)
        return {
            "external_id": sending_id,
            "substitute_id": user_reference,
            "billing_amount": float(item.get("amount", 0)),
            "estimate_amount": float(item.get("amount", 0)),
            "currency": item.get("currency") or "EUR",
            "invoice": item.get("label", ""),
            "recipient": recipient,
            "raw": item,
        }

    def _get_billings(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch invoiced lines from ``/billing/v1/recipient_items``.

        ``user_reference`` is the sending ``custom_id``: ``substitute_id`` when
        set, otherwise the local missive pk. Empty until Maileva invoices.
        """
        if self.is_mode_sandbox():
            return []
        user_reference = _provider_custom_id(kwargs)
        if not user_reference:
            return []
        items = self._recipient_item_pages({"user_reference": user_reference})
        external_id = kwargs.get("external_id")
        return [self._serialize_billing_item(item, external_id=external_id) for item in items]

    def get_billings_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._get_billings(**kwargs)

    def get_billings_registered_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._get_billings(**kwargs)

    def retrieve_billings(self, start_date, end_date, **kwargs: Any) -> dict[str, Any]:
        """Invoiced recipient lines for a date range via ``recipient_items``.

        Maileva rejects ``start_date`` / ``end_date`` on this resource. The
        documented window is ``start_invoice_date`` / ``end_invoice_date``.
        Downstream ``retrieve_billings`` update-or-creates each row against the
        matching missive (``sending_id`` → ``external_id``, ``user_reference``
        → ``substitute_id``).
        """
        if self.is_mode_sandbox():
            return {"billings": []}
        items = self._recipient_item_pages(
            {
                "start_invoice_date": self._as_billing_date(start_date),
                "end_invoice_date": self._as_billing_date(end_date),
            }
        )
        return {"billings": [self._serialize_billing_item(item) for item in items]}

    #########################################################
    # registered letter / letter - Proofs
    #########################################################

    def _retrieve_proofs(self, *, product: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch available proofs from recipients (like Mighty get_prooflist)."""
        external_id = cast(str, kwargs.get("external_id"))
        recipients = self._detail_recipients_postal(external_id, product=product)
        documents = []
        keys = self.registered_letter_proof_keys if product == "registered_letter" else self.proof_keys
        for recipient in recipients:
            for proof in keys:
                key = f"{proof}_url"
                if key in recipient:
                    filename = self.normalize_filename(f"{recipient.get('address_line_2')}_{proof}.pdf")
                    documents.append(
                        {
                            "filename": filename,
                            "url": recipient.get(key),
                        }
                    )
        return documents

    def retrieve_proofs_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._retrieve_proofs(product="letter", **kwargs)

    def retrieve_proofs_registered_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._retrieve_proofs(product="registered_letter", **kwargs)

    def _download_proof_bytes(self, url: str, *, product: str) -> bytes:
        download_url = self.get_endpoint("proofdownload", product=product) % url
        response = self._request("GET", download_url, stream=True, timeout=HTTP_DOCUMENT_TIMEOUT)
        response.raise_for_status()
        return response.content

    def download_proof_letter(self, **kwargs: Any) -> bytes:
        return self._download_proof_bytes(cast(str, kwargs.get("url")), product="letter")

    def download_proof_registered_letter(self, **kwargs: Any) -> bytes:
        return self._download_proof_bytes(cast(str, kwargs.get("url")), product="registered_letter")

    #########################################################
    # letter / registered_letter - Webhook handling
    #########################################################

    def handle_webhook_letter(self, payload: dict[str, Any] | bytes | bytearray) -> dict[str, Any]:
        return self.handle_webhook_registered_letter(payload)

    def handle_webhook_registered_letter(self, payload: dict[str, Any] | bytes | bytearray) -> dict[str, Any]:
        """Return raw payload for providerkit normalize() via fields_associations."""
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload.decode("utf-8"))
        return cast(dict[str, Any], payload)

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Map Maileva event_type / retrieve status code to a normalized event."""
        event = data.get("event_type") or data.get("event")
        return self.events_association.get(event, "unknown") if isinstance(event, str) else "unknown"

    def get_normalize_external_id(self, data: dict[str, Any]) -> str | None:
        """Missive ``external_id`` is the sending id, never the recipient UUID.

        Retrieve events set ``resource_id`` to the sending. Sending-level
        webhooks do the same. Recipient-level webhooks put the recipient
        UUID in ``resource_id``; prefer ``sending_id`` when present.
        """
        raw_detail = data.get("event_detail")
        detail: dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else {}
        sending_id = data.get("sending_id") or detail.get("sending_id")
        if sending_id:
            return str(sending_id)
        resource_name = data.get("resource_name") or ""
        resource_type = data.get("resource_type") or ""
        is_recipient_level = resource_name == "recipients" or str(resource_type).endswith("/recipients")
        if is_recipient_level:
            return None
        if data.get("resource_id"):
            return str(data["resource_id"])
        return None

    def get_normalize_recipient(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Attach the recipient for recipient-scoped postal events.

        Maileva fires webhooks at two granularities:
        - ``sendings``: the whole sending, with ``resource_custom_id`` set to the
          *sending* custom_id (not a recipient). We return ``None`` so the Django
          layer fans the lifecycle event out to every recipient.
        - ``recipients``: a single recipient, with ``resource_custom_id`` equal to
          the ``custom_id`` we sent when creating the recipient (the Django
          ``MissiveRecipient.substitute_id``). We map it so the event is attached
          directly.

        Retrieve serializes recipient statuses already keyed by that custom_id
        (``recipient.id`` / ``substitute_id``). Keep it, otherwise providerkit
        would overwrite the field with ``None`` and the event would stay
        recipient-less.
        """
        ref = _existing_recipient_ref(data.get("recipient"))
        if ref is not None:
            return ref
        if _is_recipient_resource(data):
            custom_id = data.get("resource_custom_id")
            if custom_id:
                return {"id": custom_id, "substitute_id": custom_id}
        return None

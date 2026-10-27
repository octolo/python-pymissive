import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, cast

from pymissive.utils import HTTP_DOCUMENT_TIMEOUT, _truthy
from .helpers import (
    _maileva_address_line_6,
    _notification_email,
    _provider_custom_id,
    _registered_acknowledgement_of_receipt,
    _require_maileva_line_1_or_2,
)
from .types import MailevaMixinTypingBase


class MailevaSendMixin(MailevaMixinTypingBase):
    def _sending_base_data(self, **kwargs: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": (kwargs.get("subject") or "").strip() or "Missive",
        }
        custom_id = _provider_custom_id(kwargs)
        if custom_id:
            data["custom_id"] = custom_id
        data.update(
            {
                "color_printing": _truthy(
                    kwargs.get("color_printing", self._get_config_or_env("COLOR_PRINTING", False))
                ),
                "duplex_printing": _truthy(
                    kwargs.get("duplex_printing", self._get_config_or_env("DUPLEX_PRINTING", True))
                ),
                "optional_address_sheet": kwargs.get(
                    "optional_address_sheet", self._get_config_or_env("OPTIONAL_ADDRESS_SHEET", False)
                ),
                "archiving_duration": self._normalize_archiving_duration(kwargs.get("archiving_duration")),
            }
        )
        sender = kwargs.get("sender", self._get_config_or_env("SENDER_ADDRESS", {}))
        sender_name = sender.get("name")
        sender_address = sender.get("address")
        if sender_address:
            data["sender_address_line_2"] = sender_name
            data["sender_address_line_1"] = sender_address.get("organization")
            data["sender_address_line_3"] = sender_address.get("address_line2")
            data["sender_address_line_4"] = sender_address.get("address_line1")
            data["sender_address_line_5"] = (
                sender_address.get("locality") or sender_address.get("po_box") or sender_address.get("address_line3")
            )
            data["sender_address_line_6"] = _maileva_address_line_6(sender_address, role="sender address")
            _require_maileva_line_1_or_2(
                data["sender_address_line_1"],
                data["sender_address_line_2"],
                role="sender address",
            )
            code = sender_address.get("country_code")
            data["sender_country_code"] = code.upper() if code else code

        notification_email = _notification_email(**kwargs)
        if notification_email:
            data["notification_email"] = notification_email
        if kwargs.get("custom_data") is not None:
            data["custom_data"] = kwargs["custom_data"]
        return data

    def get_letter_data(self, **kwargs: Any) -> dict[str, Any]:
        """mail/v3 sending payload (postage, envelope)."""
        data = self._sending_base_data(**kwargs)
        data["print_sender_address"] = kwargs.get(
            "print_sender_address", self._get_config_or_env("PRINT_SENDER_ADDRESS", True)
        )
        data["envelope_windows_type"] = kwargs.get(
            "envelope_windows_type", self._get_config_or_env("ENVELOPE_WINDOWS_TYPE", "DOUBLE")
        )
        priority = kwargs.get("priority")
        postage_type = (
            "urgent"
            if (priority or "").lower() == "urgent"
            else str(self._get_config_or_env("POSTAGE_TYPE", "fast")).lower()
        )
        data["postage_type"] = postage_type.upper()
        return data

    def get_registered_letter_data(self, **kwargs: Any) -> dict[str, Any]:
        """registered_mail/v4 sending payload. AR follows the missive field."""
        data = self._sending_base_data(**kwargs)
        wants_ar = _registered_acknowledgement_of_receipt(kwargs)
        data["acknowledgement_of_receipt"] = wants_ar
        if wants_ar and kwargs.get("returned_mail_scanning", self._get_config_or_env("RETURNED_MAIL_SCANNING", False)):
            data["acknowledgement_of_receipt_scanning"] = True
        if data.get("notification_email"):
            data["notification_types"] = self._get_config_or_env("NOTIFICATION_TYPES", ["ALL_MAILEVA", "ALL_LAPOSTE"])
        return data

    def _sending_data(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        if product == "letter":
            return self.get_letter_data(**kwargs)
        return self.get_registered_letter_data(**kwargs)

    def _detail_sending_postal(self, external_id: str, *, product: str) -> dict[str, Any]:
        url = self.get_endpoint("sendings", product=product)
        response = self._request("GET", url + "/" + external_id)
        response.raise_for_status()
        return response.json()

    def _create_sending_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("external_id"):
            return self._detail_sending_postal(cast(str, kwargs.get("external_id")), product=product)
        url = self.get_endpoint("sendings", product=product)
        data = self._sending_data(product=product, **kwargs)
        response = self._request("POST", url, json=data)
        self._raise_for_response(response, f"Maileva create sending failed ({url})")
        return response.json()

    def _create_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        response = self._create_sending_postal(product=product, **kwargs)
        external_id = cast(str, response.get("id"))
        recipients = cast(list[dict[str, Any]], kwargs.get("recipients"))
        response["recipients"] = self._add_recipients_postal(recipients, external_id, product=product)
        return response

    def create_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._create_postal(product="letter", **kwargs)

    def create_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        """Create sending and add recipients on the provider (used by prepare_missive)."""
        return self._create_postal(product="registered_letter", **kwargs)

    def prepare_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        """Alias for create_registered_letter (deprecated, use create_registered_letter)."""
        return self.create_registered_letter(**kwargs)

    def update_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._create_postal(product="letter", **kwargs)

    def update_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._create_postal(product="registered_letter", **kwargs)

    def _delete_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        url = self.get_endpoint("sendings", product=product) + "/" + cast(str, kwargs.get("external_id"))
        response = self._request("DELETE", url)
        return {"code": response.status_code, "message": response.text}

    def delete_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._delete_postal(product="letter", **kwargs)

    def delete_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        """DELETE sending on Maileva (draft or submitted); not the same as cancel semantics elsewhere."""
        return self._delete_postal(product="registered_letter", **kwargs)

    def _stage_postal_before_submit(self, *, product: str, **kwargs: Any) -> tuple[str, list[Any], list[Any]]:
        """Create/update sending, recipients, and documents; does not call submit."""
        response = self._create_sending_postal(product=product, **kwargs)
        external_id = cast(str, response.get("id"))
        recipients_data = cast(list[dict[str, Any]], kwargs.get("recipients"))
        recipients = self._add_recipients_postal(recipients_data, external_id, product=product)
        attachments = self._add_attachments_postal(kwargs.get("attachments", []), external_id, product=product)
        return external_id, recipients, attachments

    def _preview_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        kwargs = {
            **kwargs,
            "custom_data": kwargs.get("custom_data", "pymissive_temporary_preview"),
        }
        external_id, recipients, attachments = self._stage_postal_before_submit(product=product, **kwargs)
        return {
            "id": external_id,
            "event": "draft",
            "code": 200,
            "message": "",
            "event_date": datetime.now(dt_timezone.utc).isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }

    def preview_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._preview_postal(product="letter", **kwargs)

    def preview_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        """Same pipeline as send_registered_letter (sending, recipients, documents) without submit."""
        return self._preview_postal(product="registered_letter", **kwargs)

    def _send_postal(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        external_id, recipients, attachments = self._stage_postal_before_submit(product=product, **kwargs)
        service = f"send_{product}"
        if self._is_send_disabled():
            return self._disabled_send_response(
                service,
                external_id=external_id,
                recipients=recipients,
                attachments=attachments,
            )
        url = self.get_endpoint("submit", product=product) % external_id
        response = self._request("POST", url)
        response.raise_for_status()
        return {
            "id": external_id,
            "event": "request",
            "code": response.status_code,
            "message": response.text,
            "event_date": datetime.now(dt_timezone.utc).isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }

    def send_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._send_postal(product="letter", **kwargs)

    def send_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._send_postal(product="registered_letter", **kwargs)

    #########################################################
    # registered letter / letter - Attachments
    #########################################################

    def _add_attachment(self, *, product: str, **kwargs: Any) -> dict[str, Any]:
        attachment = kwargs.get("attachment", {})
        external_id = kwargs.get("external_id")
        priority = kwargs.get("priority", 1)
        doc_name = attachment.get("name", "document.pdf")
        content = attachment.get("content", b"")
        url = self.get_endpoint("documents", product=product) % external_id
        metadata = {"priority": priority, "name": doc_name, "shrink": True}
        files = {
            "document": (doc_name, content, "application/pdf"),
            "metadata": ("metadata", json.dumps(metadata), "application/json"),
        }
        response = self._request("POST", url, files=files, timeout=HTTP_DOCUMENT_TIMEOUT)
        response.raise_for_status()
        response = response.json()
        return {"internal_id": attachment.get("id"), "external_id": response.get("id")}

    def _add_attachments_postal(
        self, attachments: list[dict[str, Any]], external_id: str, *, product: str
    ) -> list[dict[str, Any]]:
        external_ids = []
        for priority, attachment in enumerate(attachments, start=1):
            external_ids.append(
                self._add_attachment(
                    product=product,
                    attachment=attachment,
                    external_id=external_id,
                    priority=priority,
                )
            )
        return external_ids

    def add_attachment_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._add_attachment(product="letter", **kwargs)

    def add_attachment_registered_letter(self, **kwargs: Any) -> dict[str, Any]:
        return self._add_attachment(product="registered_letter", **kwargs)

    def _get_attachments(self, *, product: str, **kwargs: Any) -> list[dict[str, Any]]:
        external_id = kwargs.get("external_id")
        url = self.get_endpoint("documents", product=product) % external_id
        response = self._request("GET", url)
        response.raise_for_status()
        return response.json()

    def get_attachments_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._get_attachments(product="letter", **kwargs)

    def get_attachments_registered_letter(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._get_attachments(product="registered_letter", **kwargs)

    def _delete_attachment(self, *, product: str, **kwargs: Any) -> bool:
        external_id = kwargs.get("external_id")
        document_id = cast(str, kwargs.get("document_id"))
        url = self.get_endpoint("documents", product=product) % external_id + "/" + document_id
        response = self._request("DELETE", url)
        response.raise_for_status()
        return True

    def delete_attachment_letter(self, **kwargs: Any) -> bool:
        return self._delete_attachment(product="letter", **kwargs)

    def delete_attachment_registered_letter(self, **kwargs: Any) -> bool:
        return self._delete_attachment(product="registered_letter", **kwargs)

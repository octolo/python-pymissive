import json
import requests
from django.utils import timezone
from .base import MissiveProviderBase
from functools import cached_property
from typing import Any


class MailevaProvider(MissiveProviderBase):
    """Maileva LRE provider (electronic registered letter, registered mail)."""

    #########################################################
    # Metadata / Configuration
    #########################################################

    name = "maileva"
    display_name = "Maileva"
    description = "LRE (electronic registered letter) and registered mail services"
    required_packages = ["requests"]
    config_keys = [
        "CLIENTID", "SECRET", "USERNAME", "PASSWORD", "SANDBOX",
        "ARCHIVING_DURATION",
        "PRINT_SENDER_ADDRESS",
        "DUPLEX_PRINTING",
        "COLOR_PRINTING",
        "POSTAGE_TYPE",
    ]
    config_defaults = {
        "SANDBOX": False,
        "ARCHIVING_DURATION": 0,
        "PRINT_SENDER_ADDRESS": True,
        "DUPLEX_PRINTING": True,
        "COLOR_PRINTING": False,
        "POSTAGE_TYPE": "FAST",
        "BASE_URL_SANDBOX": "https://api.sandbox.maileva.net",
        "BASE_URL": "https://api.maileva.com",
        "BASE_TOKEN_URL_SANDBOX": "https://connexion.sandbox.maileva.net/",
        "BASE_TOKEN_URL": "https://connexion.maileva.com",
    }
    endpoints = {
        'auth': '{base_url}/auth/realms/services/protocol/openid-connect/token',
        'sendings': '{base_url}/{postal_mode}/{version}/sendings',
        'documents': '{base_url}/{postal_mode}/{version}/sendings/%s/documents',
        'recipients': '{base_url}/{postal_mode}/{version}/sendings/%s/recipients',
        'submit': '{base_url}/{postal_mode}/{version}/sendings/%s/submit',
        'delete': '{base_url}/{postal_mode}/{version}/sendings/%s',
        'prooflist': '{base_url}/{postal_mode}/{version}/global_deposit_proofs?sending_id=%s',
        'proof': '{base_url}/{postal_mode}/{version}/global_deposit_proofs/%s',
        'proofdownload': '{base_url}/{postal_mode}/{version}%s',
        'invoice': '{base_url}/billing/v1/recipient_items?user_reference=%s',
        'subscriptions': '{base_url}/notification_center/v2/subscriptions',
    }
    events_association = {
        "ON_STATUS_ACCEPTED": "accepted",
        "ON_STATUS_REJECTED": "rejected",
        "ON_STATUS_PROCESSED": "processed",
        "ON_STATUS_PROCESSED_WITH_ERRORS": "error",
        "ON_DEPOSIT_PROOF_RECEIVED": "deposit_proof",
        "ON_GLOBAL_DEPOSIT_PROOF_RECEIVED": "deposit_proof",
        "ON_CONTENT_PROOF_RECEIVED": "proof_of_content",
        "ON_ACKNOWLEDGEMENT_OF_RECEIPT_RECEIVED": "proofs_of_delivery",
        "ON_STATUS_ARCHIVED": "archived",
        "ON_MAIN_DELIVERY_STATUS_FIRST_PRESENTATION": "attempted_delivery",
        "ON_MAIN_DELIVERY_STATUS_DELIVERED": "delivered",
        "ON_MAIN_DELIVERY_STATUS_UNDELIVERED": "undelivered",
        "ON_UNDELIVERED_MAIL_RECEIVED": "undelivered",
        "request": "request",
        "DRAFT": "request",
        "PENDING": "queued",
        "ACCEPTED": "accepted",
        "PREPARING": "processing",
    }
    fields_associations = {
        "webhook_id": "id",
        "internal_id": ("custom_id", "resource_custom_id"),
        "external_id": ("id", "resource_id",),
        "id": ("id", "resource_id"),
        "url": ["url", "callback_url"],
        "type": "resource_type",
        "occurred_at": ("event_date", "event_timestamp"),
    }
    resource_types = {
        "registered_mail/v4/sendings": "lre",
        "registered_mail/v4/recipients": "lre",
        "registered_mail/v2/sendings": "lre",
        "registered_mail/v2/recipients": "lre",
    }
    proof_keys = [
        "content_proof_embedded_document",
        "deposit_proof",
        "content_proof",
        "acknowledgement_of_receipt",
    ]
    ack_level = None

    #########################################################
    # Helpers
    #########################################################

    def get_lre_mode(self) -> str:
        return "registered_mail" if self.is_acknowledgement_of_receipt() else "mail"

    def get_version(self) -> str:
        return "v4" if self.is_acknowledgement_of_receipt() else "v2"

    def is_mode_sandbox(self) -> bool:
        return False #self._get_config_or_env("SANDBOX", False)

    def get_endpoint(self, endpoint: str, prefix: str = "api") -> str:
        return self.endpoints[endpoint].format(
            base_url=self.get_base_url(prefix),
            postal_mode=self.get_lre_mode(),
            version=self.get_version(),
        )

    def get_base_url(self, prefix: str = "api") -> str:
        if prefix == "connexion":
            return self._get_config_or_env("BASE_TOKEN_URL_SANDBOX" if self.is_mode_sandbox() else "BASE_TOKEN_URL")
        return self._get_config_or_env("BASE_URL_SANDBOX" if self.is_mode_sandbox() else "BASE_URL")

    @cached_property
    def access_token(self) -> str:
        url = self.get_endpoint('auth', prefix="connexion")
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'password',
            'username': self._get_config_or_env('USERNAME'),
            'password': self._get_config_or_env('PASSWORD'),
            'client_id': self._get_config_or_env('CLIENTID'),
            'client_secret': self._get_config_or_env('SECRET'),
        }
        response = requests.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        return response.json()['access_token']

    def _get_headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def get_resource_types(self, resource_type: str) -> str:
        return [rt for rt, tp in self.resource_types.items() if tp == resource_type]

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        rt = data.get("resource_type")
        return self.resource_types.get(rt, "unknown")

    #########################################################
    # Webhooks (generic)
    #########################################################

    def get_webhooks_by_resource_type_and_url(self, resource_type: str, url: str) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types(resource_type)
        return [
            webhook for webhook in webhooks
            if webhook.get("resource_type") in resource_types and webhook.get("callback_url") == url
        ]

    def _create_webhook_api(self, webhook_url: str, events: list[str], resource_type: list[str]) -> bool:
        url = self.get_endpoint('subscriptions')
        first_response = None
        for rt in resource_type:
            for event in events:
                data = {
                    "callback_url": webhook_url,
                    "event_type": event,
                    "resource_type": rt,
                }
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
                response.raise_for_status()
                first_response = response.json() if first_response is None else first_response
        return self.get_normalize_webhook_id({"id": first_response.get("id")})

    def retrieve_webhooks(self) -> list[dict[str, Any]]:
        url = self.get_endpoint('subscriptions')
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json().get("subscriptions", [])

    def update_webhooks(self, resource_type: str, url: str, new_callback_url: str | None = None) -> bool:
        callback_url = new_callback_url or url
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            data = {"callback_url": callback_url}
            response = requests.patch(endpoint, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
        return True

    def delete_webhooks(self, resource_type: str, url: str) -> bool:
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            endpoint = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            response = requests.delete(endpoint, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
        return True

    #########################################################
    # LRE - Recipients
    #########################################################

    def get_recipient_lre_data(self, recipient: dict[str, Any]) -> dict[str, Any]:
        address = recipient.get("address")
        if not address:
            raise ValueError("LRE recipient requires address")
        data = {
            "custom_id": recipient.get("id"),
            "address_line_1": address.get("organization"),
            "address_line_2": recipient.get("name"),
            "address_line_3": address.get("address_line2"),
            "address_line_4": address.get("address_line1"),
            "address_line_5": address.get("locality") or address.get("po_box"),
            "address_line_6": f"{address.get('postal_code')} {address.get('city')}",
            "country_code": address.get("country_code"),
        }
        if address.get("sorting_code"):
            data["address_line_6"] += " " + address.get("sorting_code")
        return data

    def _detail_recipients_lre(self, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        response = response.json()
        return response.get("recipients", [])

    def add_recipient_lre(self, recipient: dict[str, Any], external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        data = self.get_recipient_lre_data(recipient)
        response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        response = response.json()
        return {
            "internal_id": recipient.get("id"),
            "external_id": response.get("id"),
        }

    def update_recipient_lre(self, recipient: dict[str, Any], external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        data = self.get_recipient_lre_data(recipient)
        response = requests.patch(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        response = response.json()
        return {
            "internal_id": recipient.get("id"),
            "external_id": response.get("id"),
        }

    def _add_recipients_lre(self, recipients: list[dict[str, Any]], external_id: str) -> bool:
        external_ids = []
        for recipient in recipients:
            if recipient.get("external_id"):
                response = self.update_recipient_lre(recipient, external_id)
            else:
                response = self.add_recipient_lre(recipient, external_id)
            external_ids.append(response)
        return external_ids

    def delete_recipient_lre(self, recipient, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def delete_recipients_lre(self, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    #########################################################
    # LRE - Sendings (create, update, delete, send)
    # Maileva: no separate "cancel sending" API; removing a sending uses HTTP DELETE (delete_lre).
    #########################################################

    def is_acknowledgement_of_receipt(self, **kwargs: Any) -> bool:
        if not self.ack_level:
            self.ack_level = kwargs.get("acknowledgement")
        return self.ack_level == "acknowledgement_of_receipt"

    def get_lre_data(self, **kwargs: Any) -> dict[str, Any]:
        data = {
            "name": kwargs.get("subject"),
            "custom_id": str(kwargs.get("id")),
            "color_printing": kwargs.get("color_printing", self._get_config_or_env("COLOR_PRINTING", False)),
            "duplex_printing": kwargs.get("duplex_printing", self._get_config_or_env("DUPLEX_PRINTING", True)),
            "optional_address_sheet": kwargs.get("optional_address_sheet", self._get_config_or_env("OPTIONAL_ADDRESS_SHEET", False)),
            "print_sender_address": kwargs.get("print_sender_address", self._get_config_or_env("PRINT_SENDER_ADDRESS", True)),
            "archiving_duration": kwargs.get("archiving_duration", self._get_config_or_env("ARCHIVING_DURATION", 0)),
            'envelope_windows_type': kwargs.get("envelope_windows_type", self._get_config_or_env("ENVELOPE_WINDOWS_TYPE", "DOUBLE")),
        }
        sender = kwargs.get("sender", self._get_config_or_env("SENDER_ADDRESS", {}))
        sender_name = sender.get("name")
        sender_address = sender.get("address")
        if sender_address:
            data["sender_address_line_2"] = sender_name
            data["sender_address_line_1"] = sender_address.get("organization")
            data["sender_address_line_3"] = sender_address.get("address_line2")
            data["sender_address_line_4"] = sender_address.get("address_line1")
            data["sender_address_line_5"] = sender_address.get("locality") or sender_address.get("po_box")
            data["sender_address_line_6"] = f"{sender_address.get('postal_code')} {sender_address.get('city')}"
            data["sender_country_code"] = sender_address.get("country_code")
            if sender_address.get("sorting_code"):
                data["sender_address_line_6"] += " " + sender_address.get("sorting_code")

        if kwargs.get("notification_email"):
            data["notification_email"] = kwargs.get("notification_email", self._get_config_or_env("NOTIFICATION_EMAIL", ""))
            data["notification_types"] = self._get_config_or_env("NOTIFICATION_TYPES", ["ALL_MAILEVA", "ALL_LAPOSTE"])
        if self.is_acknowledgement_of_receipt():
            data["returned_mail_scanning"] = kwargs.get("returned_mail_scanning", self._get_config_or_env("RETURNED_MAIL_SCANNING", False))
            data["acknowledgement_of_receipt"] = True
            priority = kwargs.get("priority")
            data["postage_type"] = "urgent" if (priority or "").lower() == "urgent" else self._get_config_or_env("POSTAGE_TYPE", "fast")
        if kwargs.get("custom_data") is not None:
            data["custom_data"] = kwargs["custom_data"]
        return data

    def _detail_lre(self, external_id: str) -> bool:
        url = self.get_endpoint('sendings')
        response = requests.get(url + "/" + external_id, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def _create_lre(self, **kwargs: Any) -> bool:
        if kwargs.get("external_id"):
            return self._detail_lre(kwargs.get("external_id"))
        url = self.get_endpoint('sendings')
        data = self.get_lre_data(**kwargs)
        response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def create_lre(self, **kwargs: Any) -> bool:
        """Create sending and add recipients on the provider (used by prepare_missive)."""
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        return response

    def prepare_lre(self, **kwargs: Any) -> bool:
        """Alias for create_lre (deprecated, use create_lre)."""
        return self.create_lre(**kwargs)

    def update_lre(self, **kwargs: Any) -> bool:
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        return response

    def delete_lre(self, **kwargs: Any) -> bool:
        """DELETE sending on Maileva (draft or submitted); not the same as cancel semantics elsewhere."""
        self.is_acknowledgement_of_receipt(**kwargs)
        url = self.get_endpoint('sendings') + "/" + kwargs.get("external_id")
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        return {"code": response.status_code, "message": response.text}

    def _stage_lre_before_submit(self, **kwargs: Any) -> tuple[str, list[Any], list[Any]]:
        """Create/update sending, recipients, and documents; does not call submit."""
        self.is_acknowledgement_of_receipt(**kwargs)
        response = self._create_lre(**kwargs)
        external_id = response.get("id")
        recipients = self._add_recipients_lre(kwargs.get("recipients"), external_id)
        attachments = self._add_attachments_lre(kwargs.get("attachments", []), external_id)
        return external_id, recipients, attachments

    def preview_lre(self, **kwargs: Any) -> dict[str, Any]:
        """Same pipeline as send_lre (sending, recipients, documents) without submit."""
        kwargs = {
            **kwargs,
            "custom_data": kwargs.get("custom_data", "pymissive_temporary_preview"),
        }
        external_id, recipients, attachments = self._stage_lre_before_submit(**kwargs)
        print("external_id", external_id)
        return {
            "id": external_id,
            "event": "draft",
            "code": 200,
            "message": "",
            "event_date": timezone.now().isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }

    def send_lre(self, **kwargs: Any) -> bool:
        external_id, recipients, attachments = self._stage_lre_before_submit(**kwargs)
        url = self.get_endpoint('submit') % external_id
        response = requests.post(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        data = {
            "id": external_id,
            "event": "request" if response.status_code == 200 else "error",
            "code": response.status_code,
            "message": response.text,
            "event_date": timezone.now().isoformat(),
            "attachments": attachments,
            "recipients": recipients,
        }
        return data

    #########################################################
    # LRE - Attachments
    #########################################################

    def _add_attachments_lre(self, attachments: list[dict[str, Any]], external_id: str) -> bool:
        external_ids = []
        for priority, attachment in enumerate(attachments, start=1):
            external_ids.append(self.add_attachment_lre(
                attachment=attachment,
                external_id=external_id,
                priority=priority,
            ))
        return external_ids

    def add_attachment_lre(self, **kwargs: Any) -> dict[str, Any]:
        attachment = kwargs.get("attachment", {})
        external_id = kwargs.get("external_id")
        priority = kwargs.get("priority", 1)
        doc_name = attachment.get("name", "document.pdf")
        content = attachment.get("content", b"")
        url = self.get_endpoint('documents') % external_id
        metadata = {"priority": priority, "name": doc_name, "shrink": True}
        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }
        files = {
            'document': (doc_name, content, 'application/pdf'),
            'metadata': ('metadata', json.dumps(metadata), 'application/json'),
        }
        response = requests.post(url, headers=headers, files=files, timeout=60)
        response.raise_for_status()
        response = response.json()
        return {"internal_id": attachment.get("id"), "external_id": response.get("id")}

    def get_attachments_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        url = self.get_endpoint('documents') % external_id
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def delete_attachment_lre(self, **kwargs: Any) -> bool:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        document_id = kwargs.get("document_id")
        url = self.get_endpoint('documents') % external_id + "/" + document_id
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return True

    #########################################################
    # LRE - Webhooks
    #########################################################

    def create_webhook_lre(self, webhook_data: dict[str, Any]) -> str:
        webhook_url = webhook_data.get("url")
        events = list([event for event in self.events_association.keys() if event.startswith("ON_")])
        resource_types = self.get_resource_types("lre")
        response = self._create_webhook_api(webhook_url, events, resource_types)
        return response

    def _retrieve_webhooks_lre(self) -> list[dict[str, Any]]:
        webhooks = self.retrieve_webhooks()
        resource_types = self.get_resource_types("lre")
        return [
            webhook for webhook in webhooks
            if webhook.get("resource_type") in resource_types
        ]

    def _raw_id_from_webhook_id(self, webhook_id: str | None) -> str | None:
        """Extract raw provider id from normalized webhook_id (e.g. 'maileva-123' -> '123')."""
        if not webhook_id:
            return None
        parts = str(webhook_id).split("-", 1)
        return parts[1] if len(parts) > 1 else parts[0]

    def delete_webhook_lre(self, webhook_data: dict[str, Any]) -> None:
        url = webhook_data.get("url") or webhook_data.get("callback_url")
        if not url:
            raw_id = self._raw_id_from_webhook_id(
                webhook_data.get("webhook_id") or webhook_data.get("id")
            )
            if raw_id:
                for w in self.retrieve_webhooks():
                    if str(w.get("id")) == str(raw_id):
                        url = w.get("callback_url")
                        break
        if not url:
            raise ValueError("Cannot delete webhook: no URL and could not derive from webhook_id")
        return self.delete_webhooks("lre", url)

    def update_webhook_lre(self, webhook_data: dict[str, Any]) -> dict[str, Any]:
        new_url = webhook_data.get("url") or webhook_data.get("callback_url")
        search_url = new_url
        if not search_url:
            raw_id = self._raw_id_from_webhook_id(
                webhook_data.get("webhook_id") or webhook_data.get("id")
            )
            if raw_id:
                for w in self.retrieve_webhooks():
                    if str(w.get("id")) == str(raw_id):
                        search_url = w.get("callback_url")
                        break
        if not search_url:
            raise ValueError("Cannot update webhook: no URL and could not derive from webhook_id")
        return self.update_webhooks("lre", search_url, new_url or search_url)

    #########################################################
    # LRE - Retrieve / Events
    #########################################################

    def get_normalize_events(self, data):
        if "events" in data:
            return data.get("events")
        return None

    def _serialize_events_lre(self, recipients, detail_lre):
        print("detail_lre", detail_lre)
        events = []
        for recipient in recipients:
            if "statuses" in recipient:
                for status in recipient.get("statuses", []):
                    events.append({
                        "resource_id": detail_lre.get("id"),
                        "event": status.get("code"),
                        "event_date": status.get("date"),
                        "recipient": {"id": recipient.get("custom_id")},
                    })
            elif "status" in recipient:
                events.append({
                    "recipient": {"id": recipient.get("custom_id")},
                    "resource_id": detail_lre.get("id"),
                    "event": recipient.get("status"),
                    "event_date": detail_lre.get("submission_date"),
                })
        return events

    def retrieve_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        detail_lre = self._detail_lre(external_id)
        recipients_lre = self._detail_recipients_lre(external_id)
        return {
            **detail_lre,
            "events": self._serialize_events_lre(recipients_lre, detail_lre),
        }

    #########################################################
    # LRE - Billings
    #########################################################

    def get_billings_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch invoice from Maileva billing API (user_reference = custom_id from sending)."""
        if self.is_mode_sandbox():
            return []
        self.is_acknowledgement_of_receipt(**kwargs)
        external_id = kwargs.get("external_id")
        detail = self._detail_lre(external_id)
        user_reference = detail.get("custom_id") or external_id
        url = self.get_endpoint("invoice") % user_reference
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        inv = data.get("invoice")
        items = (inv.get("items") if isinstance(inv, dict) else None) or data.get("items") or []
        billings = []
        for item in items:
            amount = float(item.get("amount", 0))
            billings.append({
                "external_id": external_id,
                "billing_amount": amount,
                "estimate_amount": amount,
                "currency": "EUR",
                "invoice": item.get("label", ""),
                "recipient": {"id": item.get("recipient_id")} if item.get("recipient_id") else None,
                "raw": item,
            })
        if not billings:
            billings.append({
                "external_id": external_id,
                "billing_amount": None,
                "estimate_amount": None,
                "currency": "EUR",
                "invoice": str(data),
                "raw": data,
            })
        return billings

    #########################################################
    # LRE - Proofs
    #########################################################

    def retrieve_proofs_lre(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch available proofs from recipients (like Mighty get_prooflist)."""
        self.is_acknowledgement_of_receipt(**kwargs)
        recipients = self._detail_recipients_lre(kwargs.get("external_id"))
        documents = []
        for recipient in recipients:
            for proof in self.proof_keys:
                key = f"{proof}_url"
                if key in recipient:
                    filename = self.normalize_filename(f"{recipient.get('address_line_2')}_{proof}.pdf")
                    documents.append({
                        "filename": filename,
                        "url": recipient.get(key),
                    })
        return documents

    def download_proof_lre(self, **kwargs: Any) -> bool:
        self.is_acknowledgement_of_receipt(**kwargs.get("data", {}))
        filename = kwargs.get("filename")
        url = kwargs.get("url")
        url = self.get_endpoint('proofdownload') % url
        response = requests.get(url, stream=True, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.content

    #########################################################
    # LRE - Webhook handling
    #########################################################

    def handle_webhook_lre(self, payload: dict[str, Any] | bytes) -> dict[str, Any]:
        """Return raw payload for providerkit normalize() via fields_associations."""
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload.decode("utf-8"))
        return payload

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Map Maileva event_type to normalized event."""
        return self.events_association.get(
            data.get("event_type") or data.get("event"), "unknown"
        )

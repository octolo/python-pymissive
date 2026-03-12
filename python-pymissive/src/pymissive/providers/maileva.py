import json
import requests
from django.utils import timezone
from .base import MissiveProviderBase
from functools import cached_property
from typing import Any


class MailevaProvider(MissiveProviderBase):
    name = "maileva"
    display_name = "Maileva"
    description = "Electronic postal mail and registered mail services"
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
        'cancel': '{base_url}/{postal_mode}/{version}/sendings/%s',
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
        # No maileva events
        "request": "request",
        "DRAFT": "request",
        "PENDING": "queued",
        "ACCEPTED": "accepted",
        "PREPARING": "processing",
    }
    fields_associations = {
        "internal_id": ("custom_id", "resource_custom_id"),
        "external_id": ("id", "resource_id",),
        "id": ("id", "resource_id"),
        "url": "callback_url",
        "type": "resource_type",
        "occurred_at": ("event_date", "event_timestamp"),
        "description": "event_type",
    }
    resource_types = {
        "registered_mail/v4/sendings": "postal",
        "registered_mail/v4/recipients": "postal",
        "registered_mail/v2/sendings": "postal",
        "registered_mail/v2/recipients": "postal",
    }
    ack_level = None

    #########################################################
    # Helpers
    #########################################################

    def get_postal_mode(self) -> str:
        return "registered_mail" if self.is_postal_registered() else "mail"

    def get_version(self) -> str:
        return "v4" if self.is_postal_registered() else "v2"

    def is_mode_sandbox(self) -> bool:
        return self._get_config_or_env("SANDBOX", False)

    def get_endpoint(self, endpoint: str, prefix: str = "api") -> str:
        return self.endpoints[endpoint].format(
            base_url=self.get_base_url(prefix),
            postal_mode=self.get_postal_mode(),
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

    def get_resource_types(self, resource_type: str) -> str:
        return [rt for rt, tp in self.resource_types.items() if tp == resource_type]

    def _get_headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        rt = data.get("resource_type")
        return self.resource_types.get(rt, "unknown")

    #########################################################
    # Webhooks
    #########################################################

    def get_webhooks_by_resource_type_and_url(self, resource_type: str, url: str) -> list[dict[str, Any]]:
        webhooks = self.get_webhooks()
        resource_types = self.get_resource_types(resource_type)
        return [
            webhook for webhook in webhooks 
            if webhook.get("resource_type") in resource_types and webhook.get("callback_url") == url
        ]

    def set_webhook(self, webhook_url: str, events: list[str], resource_type: list[str]) -> bool:
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

    def get_webhooks(self) -> list[dict[str, Any]]:
        url = self.get_endpoint('subscriptions')
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json().get("subscriptions", [])

    def update_webhooks(self, resource_type: str, url: str,) -> bool:
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            url = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            data = {"callback_url": url,}
            response = requests.patch(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
        return True

    def delete_webhooks(self, resource_type: str, url: str) -> bool:
        webhooks = self.get_webhooks_by_resource_type_and_url(resource_type, url)
        for webhook in webhooks:
            url = self.get_endpoint('subscriptions') + "/" + webhook.get("id")
            response = requests.delete(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
        return True

    #########################################################
    # Postal Registered
    #########################################################

    def get_recipient_postal_data(self, recipient: dict[str, Any]) -> dict[str, Any]:
        address = recipient.get("address")
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

    def _detail_recipients_postal(self, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def update_recipient_postal(self, recipient: dict[str, Any], external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        data = self.get_recipient_postal_data(recipient)
        response = requests.patch(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        response = response.json()
        return {
            "internal_id": recipient.get("id"),
            "external_id": response.get("id"),
        }

    def add_recipient_postal(self, recipient: dict[str, Any], external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        data = self.get_recipient_postal_data(recipient)
        response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        response = response.json()
        return {
            "internal_id": recipient.get("id"),
            "external_id": response.get("id"),
        }

    def _add_recipients_postal(self, recipients: list[dict[str, Any]], external_id: str) -> bool:
        external_ids = []
        for recipient in recipients:
            if recipient.get("external_id"):
                response = self.update_recipient_postal(recipient, external_id)
            else:
                response = self.add_recipient_postal(recipient, external_id)
            external_ids.append(response)
        return external_ids

    def delete_recipients_postal(self, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def delete_recipient_postal(self, recipient, external_id: str) -> bool:
        url = self.get_endpoint('recipients') % external_id + "/" + recipient.get("external_id")
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def is_postal_registered(self, **kwargs: Any) -> bool:
        if not self.ack_level:
            self.ack_level = kwargs.get("acknowledgement")
        return self.ack_level == "acknowledgement_of_receipt"

    def get_postal_data(self, **kwargs: Any) -> dict[str, Any]:
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
        sender_address = kwargs.get("sender_address", self._get_config_or_env("SENDER_ADDRESS", {}))
        if sender_address:
            data["sender_address_line_1"] = sender_address.get("organization")
            data["sender_address_line_2"] = kwargs.get("sender_name")
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
        if self.is_postal_registered():
            data["returned_mail_scanning"] = kwargs.get("returned_mail_scanning", self._get_config_or_env("RETURNED_MAIL_SCANNING", False))
            data["acknowledgement_of_receipt"] = True
            priority = kwargs.get("priority")
            data["postage_type"] = "urgent" if (priority or "").lower() == "urgent" else self._get_config_or_env("POSTAGE_TYPE", "fast")
        return data

    def _detail_postal(self, external_id: str) -> bool:
        url = self.get_endpoint('sendings')
        response = requests.get(url + "/" + external_id, headers=self._get_headers(), timeout=30)	
        response.raise_for_status()
        return response.json()

    def _create_postal(self, **kwargs: Any) -> bool:
        if kwargs.get("external_id"):
            return self._detail_postal(kwargs.get("external_id"))
        url = self.get_endpoint('sendings')
        data = self.get_postal_data(**kwargs)
        response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
        print(response.content)
        response.raise_for_status()
        return response.json()

    def prepare_postal(self, **kwargs: Any) -> bool:
        self.is_postal_registered(**kwargs)
        response = self._create_postal(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_postal(kwargs.get("recipients"), external_id)
        return response

    def update_postal(self, **kwargs: Any) -> bool:
        self.is_postal_registered(**kwargs)
        response = self._create_postal(**kwargs)
        external_id = response.get("id")
        response["recipients"] = self._add_recipients_postal(kwargs.get("recipients"), external_id)
        return response

    def cancel_postal(self, **kwargs: Any) -> bool:
        self.is_postal_registered(**kwargs)
        url = self.get_endpoint('sendings') + "/" + kwargs.get("external_id")
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        return {"code": response.status_code, "message": response.text}

    def status_postal(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_postal_registered(**kwargs)
        external_id = kwargs.get("external_id")
        response = self._detail_recipients_postal(external_id)
        recipients = response.get("recipients", [])

        events = []
        for recipient in recipients:
            rec_id = recipient.get("id")
            internal_id = next(
                (
                    r.get("id")
                    for r in kwargs.get("recipients", [])
                    if str(r.get("external_id")) == str(rec_id)
                ),
                None,
            )
            for status in recipient.get("statuses", []):
                evt = {
                    "external_id": external_id,
                    "event": status.get("code"),
                    "occurred_at": status.get("date"),
                    "description": status.get("code"),
                    "raw": status,
                    "recipient_id": rec_id,
                }
                if internal_id is not None:
                    evt["internal_id"] = internal_id
                events.append(evt)
        return events


    def send_postal(self, **kwargs: Any) -> bool:
        self.is_postal_registered(**kwargs)
        response = self._create_postal(**kwargs)
        external_id = response.get("id")
        recipients = self._add_recipients_postal(kwargs.get("recipients"), external_id)
        attachments = self._add_attachments_postal(kwargs.get("attachments", []), external_id)
        url = self.get_endpoint('submit') % external_id
        response = requests.post(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return {
            "id": external_id,
            "event": "request" if response.status_code == 200 else "error",
            "code": response.status_code,
            "message": response.text,
            "occurred_at": timezone.now().isoformat(),
            "description": response.text,
            "user_action": True,
            "attachments": attachments,
            "recipients": recipients,
        }

    def _add_attachments_postal(self, attachments: list[dict[str, Any]], external_id: str) -> bool:
        external_ids = []
        for priority, attachment in enumerate(attachments, start=1):
            external_ids.append(self.add_attachment_postal(
                attachment=attachment,
                external_id=external_id,
                priority=priority,
            ))
        return external_ids

    def add_attachment_postal(self, **kwargs: Any) -> dict[str, Any]:
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

    def get_attachments_postal(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.is_postal_registered(**kwargs)
        external_id = kwargs.get("external_id")
        url = self.get_endpoint('documents') % external_id
        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def delete_attachment_postal(self, **kwargs: Any) -> bool:
        self.is_postal_registered(**kwargs)
        external_id = kwargs.get("external_id")
        document_id = kwargs.get("document_id")
        url = self.get_endpoint('documents') % external_id + "/" + document_id
        response = requests.delete(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()
        return True
    
    def set_webhook_postal(self, webhook_data: dict[str, Any]) -> str:
        webhook_url = webhook_data.get("url")
        events = list([event for event in self.events_association.keys() if event.startswith("ON_")])
        resource_types = self.get_resource_types("postal")
        response = self.set_webhook(webhook_url, events, resource_types)
        return response
   
    def get_webhook_postal(self) -> dict[str, Any]:
        webhooks = self.get_webhooks()
        resource_types = self.get_resource_types("postal")
        return [
            webhook for webhook in webhooks 
            if webhook.get("resource_type") in resource_types
        ]

    def delete_webhook_postal(self, webhook_data: dict[str, Any]) -> None:
        url = webhook_data.get("url")
        return self.delete_webhooks("postal", url)

    def update_webhook_postal(self, webhook_data: dict[str, Any]) -> dict[str, Any]:
        subscription_id = webhook_data.get("id") or webhook_data.get("webhook_id", "")
        url = self.get_endpoint('subscriptions') + "/" + subscription_id
        data = {
            "callback_url": webhook_data.get("url"),
        }
        response = requests.patch(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        response = response.json()
        return response.get("id")

    def get_recipient_postal(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Extract recipient data from webhook payload."""
        recipient = payload.get("recipient") or payload.get("resource_data", {}).get("recipient")
        if not recipient:
            return None
        return {
            "internal_id": recipient.get("custom_id"),
            "recipient_id": recipient.get("id"),
        }

    def handle_webhook_postal(self, payload: dict[str, Any] | bytes) -> dict[str, Any]:
        """Return raw payload for providerkit normalize() via fields_associations."""
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload.decode("utf-8"))
        recipient = self.get_recipient_postal(payload)
        if recipient:
            payload = {**payload, "recipients": [recipient]}
        return payload

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Map Maileva event_type to normalized event."""
        return self.events_association.get(
            data.get("event_type") or data.get("event"), "unknown"
        )

    def get_proofs_postal(self, **kwargs: Any) -> bool:
        return True

    def download_proof_postal(self, **kwargs: Any) -> bool:
        return True

    def get_external_id_postal(self, **kwargs: Any) -> bool:
        return True

    def get_billing_amount_postal(self, **kwargs: Any) -> bool:
        return True
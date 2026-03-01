import json
import requests

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
        "SANDBOX": True,
        "ARCHIVING_DURATION": 0,
        "PRINT_SENDER_ADDRESS": True,
        "DUPLEX_PRINTING": True,
        "COLOR_PRINTING": False,
        "POSTAGE_TYPE": "FAST",
    }
    endpoints = {
        'auth': '{base_url}/auth/realms/services/protocol/openid-connect/token',
        'sendings': '{base_url}/registered_mail/v4/sendings',
        'documents': '{base_url}/registered_mail/v4/sendings/%s/documents',
        'recipients': '{base_url}/registered_mail/v4/sendings/%s/recipients',
        'submit': '{base_url}/registered_mail/v4/sendings/%s/submit',
        'cancel': '{base_url}/registered_mail/v4/sendings/%s',
        'prooflist': '{base_url}/registered_mail/v4/global_deposit_proofs?sending_id=%s',
        'proof': '{base_url}/registered_mail/v4/global_deposit_proofs/%s',
        'proofdownload': '{base_url}/registered_mail/v4%s',
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
    }
    fields_associations = {
        "id": "id",
        "url": "callback_url",
        "type": "resource_type",
    }
    resource_types = {
        "registered_mail/v4/sendings": "postal_registered",
        "registered_mail/v4/recipients": "postal_registered",
        "registered_mail/v2/sendings": "postal_registered",
        "registered_mail/v2/recipients": "postal_registered",
    }

    #########################################################
    # Helpers
    #########################################################

    def is_mode_sandbox(self) -> bool:
        return self._get_config_or_env("SANDBOX", False)

    def get_endpoint(self, endpoint: str, prefix: str = "api") -> str:
        return self.endpoints[endpoint].format(base_url=self.get_base_url(prefix))

    def get_base_url(self, prefix: str = "api") -> str:
        url = "maileva.com"
        if self.is_mode_sandbox():
            url = "sandbox.maileva.net"
        return f"https://{prefix}.{url}"

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
        for rt in resource_type:
            for event in events:
                data = {
                    "callback_url": webhook_url,
                    "event_type": event,
                    "resource_type": rt,
                }
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
                response.raise_for_status()
        return True

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

    def prepare_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def update_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def cancel_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def status_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def send_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def add_attachment_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def get_attachments_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def delete_attachment_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def add_sender_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def add_recipients_postal_registered(self, **kwargs: Any) -> bool:
        return True
    
    def set_webhook_postal_registered(self, webhook_data: dict[str, Any]) -> str:
        webhook_url = webhook_data.get("url")
        events = list(self.events_association.keys())
        resource_types = self.get_resource_types("postal_registered")
        response = self.set_webhook(webhook_url, events, resource_types)
        return response
   
    def get_webhook_postal_registered(self) -> dict[str, Any]:
        webhooks = self.get_webhooks()
        resource_types = self.get_resource_types("postal_registered")
        return [
            webhook for webhook in webhooks 
            if webhook.get("resource_type") in resource_types
        ]

    def delete_webhook_postal_registered(self, webhook_data: dict[str, Any]) -> None:
        url = webhook_data.get("url")
        return self.delete_webhooks("postal_registered", url)

    def update_webhook_postal_registered(self, webhook_data: dict[str, Any]) -> dict[str, Any]:
        events = list(self.events_association.keys())
        resource_types = self.get_resource_types("postal_registered")
        subscription_id = webhook_data.get("id") or webhook_data.get("webhook_id", "")
        url = self.get_endpoint('subscriptions') + "/" + subscription_id
        data = {
            "event_types": events,
            "callback_url": webhook_data.get("url"),
            "resource_type": resource_types[0],
        }
        response = requests.put(url, headers=self._get_headers(), json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_recipient_postal_registered(self, payload: dict[str, Any]) -> str:
        return None
    
    def handle_webhook_postal_registered(self, payload: dict[str, Any] | bytes) -> dict[str, Any]:
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload.decode("utf-8"))
        return {
            "recipients": self.get_recipient_postal_registered(payload),
            "event": self.events_association.get(payload.get("event_type"), "unknown"),
            "occurred_at": payload.get("event_date"),
            "external_id": payload.get("resource_id"),
            "description": payload.get("event_type"),
            "trace": payload,
        }

    def get_proofs_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def download_proof_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def get_external_id_postal_registered(self, **kwargs: Any) -> bool:
        return True

    def get_billing_amount_postal_registered(self, **kwargs: Any) -> bool:
        return True
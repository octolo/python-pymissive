"""Partner providers (SMS, Email, Voice) - Simple implementations."""

import json
from datetime import datetime
from typing import Any, Dict

import requests

from pymissive.config import ALL_EVENTS
from pymissive.utils import is_disable_send

from .base import MissiveProviderBase


class PartnerProvider(MissiveProviderBase):
    """Partner provider (SMS, Email, Voice) - SMSPartner / MailPartner / VoicePartner."""

    #########################################################
    # Metadata / Configuration
    #########################################################

    name = "partner"
    display_name = "Partner"
    description = "French multi-service solution (SMS, Email, Voice)"
    site_url = "https://www.smspartner.fr/"
    documentation_url = "https://www.docpartner.dev/"
    required_packages = ["requests"]
    config_keys = ["SMS_API_KEY", "SENDER_NAME"]
    config_defaults = {
        "SENDER_NAME": "Missive",
    }
    _api_base_sms = "https://api.smspartner.fr/v1"
    _api_base_voice = "https://api.voicepartner.fr/v1"
    _api_base_email = "https://api.mailpartner.fr/v1"

    events_association = {
        "delivered": "delivered",
        "not delivered": "failed",
        "waiting": "pending",
        "sent": "sent",
    }

    fields_associations = {
        "external_id": ["message_id", "messageId", "msgId"],
        "cost": "cost",
        "currency": "currency",
        "phone": ["phone", "e164", "number"],
        "occurred_at": ("date", "occurred_at"),
        "event": "status",
        "billing_amount": "cost",
        "estimate_amount": "cost",
    }

    #########################################################
    # Helpers
    #########################################################

    def _request(self, url: str, method: str, data: dict = None) -> dict:
        """Request to the API."""
        kwargs: dict[str, Any] = {"headers": {"Content-Type": "application/json"}}
        if method.upper() == "GET":
            kwargs["params"] = data
        else:
            kwargs["json"] = data
        response = requests.request(method, url, **kwargs)
        return response.json()

    #########################################################
    # Normalization
    #########################################################

    def _recipient(self, data):
        if "phoneNumber" in data:
            return {"phone": data.get("phoneNumber")}
        if "phone" in data:
            return {"phone": data.get("phone")}
        return None

    def get_normalize_recipient(self, data):
        return self._recipient(data)

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Return the normalized event of webhook/SMS."""
        if "event" in data:
            return self.events_association.get(data.get("event"), "unknown")
        if "status" in data:
            return self.events_association.get(data.get("status"), "unknown")
        if "success" in data:
            return "sent" if data.get("success") else "failed"
        return "unknown"

    def get_normalize_occurred_at(self, data: dict[str, Any]) -> str:
        """Return the normalized occurred_at as ISO string."""
        timestamp = data.get("date") or data.get("occurred_at") or datetime.now().timestamp()
        return datetime.fromtimestamp(int(timestamp)).isoformat()

    def get_normalize_invoice(self, data: dict[str, Any]) -> str:
        for key in ["nb_sms", "nb_emails", "nb_voice", "nbSms", "nbEmails", "nbVoice"]:
            if key in data:
                return f"{key}: {data.get(key)}"
        return None

    def get_normalize_events(self, data):
        if "events" in data:
            return [
                {
                    **event,
                    "message_id": data.get("message_id"),
                    "recipient": self._recipient(event),
                }
                for event in data.get("events")
            ]
        return None

    def get_normalize_billings(self, data):
        return [data]

    #########################################################
    # SMS - Send
    #########################################################

    def send_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Send SMS."""
        data = {
            "apiKey": self._get_config_or_env("SMS_API_KEY"),
            "sender": kwargs.get("sender", {}).get("phone") or kwargs.get("sender", {}).get("name") or self._get_config_or_env("SENDER_NAME", "Missive"),
            "message": kwargs["body_text"],
            "phoneNumbers": ",".join([str(rp["phone"]) for rp in kwargs.get("recipients", [])]),
            "isStopSms": kwargs.get("is_stop_sms", self._get_config_or_env("IS_STOP_SMS", 0)),
            "isUnicode": kwargs.get("is_unicode", self._get_config_or_env("IS_UNICODE", 0)),
            "sandbox": kwargs.get("sandbox", self._get_config_or_env("SANDBOX", 0)),
            "_format": kwargs.get("format", self._get_config_or_env("FORMAT", "json")),
            "tag": kwargs.get("tag"),
            "urlDlr": kwargs.get("webhook_url"),
            "urlResponse": kwargs.get("webhook_url"),
        }
        if is_disable_send():
            return self._disabled_send_response("send_sms", external_id=kwargs.get("external_id"))
        response = self._request(self._api_base_sms + "/send", "POST", data)
        response["occurred_at"] = datetime.now().timestamp()
        return response

    #########################################################
    # SMS - Retrieve / Status
    #########################################################

    def _retrieve_sms(self, **kwargs: Any) -> Dict[str, Any]:
        data = {
            "apiKey": self._get_config_or_env("SMS_API_KEY"),
            "messageId": kwargs.get("external_id"),
        }
        response = self._request(self._api_base_sms + "/bulk-status", "GET", data)
        return response

    def retrieve_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Status SMS."""
        response = self._retrieve_sms(**kwargs)
        return {
            "message_id": kwargs.get("external_id"),
            "events": response.get("StatutResponse_List"),
        }

    #########################################################
    # SMS - Webhook
    #########################################################

    def handle_webhook_sms(self, payload: bytes | dict | list) -> dict | list:
        """Normalize raw (bytes) or pass through pre-normalized (list/dict)."""
        if isinstance(payload, (bytes, bytearray)):
            return json.loads(payload.decode("utf-8"))
        return payload

    #########################################################
    # SMS - Billings
    #########################################################

    def get_billings_sms(self, **kwargs: Any) -> dict | list:
        external_id = kwargs.get("external_id")
        """Fetch billings from bulk-status response."""
        external_id = kwargs.get("external_id")
        response = self._retrieve_sms(external_id=external_id)
        if "StatutResponse_List" in response:
            return [
                {**item, "message_id": external_id}
                for item in response.get("StatutResponse_List")
            ]
        return None
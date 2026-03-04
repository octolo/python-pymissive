"""Partner providers (SMS, Email, Voice) - Simple implementations."""

import base64
import os
from typing import Any, Dict, Optional

import requests
import json
from datetime import datetime
from .base import MissiveProviderBase


class PartnerProvider(MissiveProviderBase):
    """Abstract base class for Partner providers (SMS, Email, Voice)."""
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
        "external_id": ["message_id", "msgId", "messageId"],
        "cost": "cost",
        "currency": "currency",
        "phone": ["phone", "e164", "number"],
        "occurred_at": "date",
        "event": "status",
        "billing_amount": "cost",
    }

    def _request(self, url: str, method: str, data: dict = None) -> dict:
        """Request to the API."""
        kwargs: dict[str, Any] = {"headers": {"Content-Type": "application/json"}}
        if method.upper() == "GET":
            kwargs["params"] = data
        else:
            kwargs["json"] = data
        response = requests.request(method, url, **kwargs)
        return response.json()

    def get_normalize_occurred_at(self, data: dict[str, Any]) -> str:
        """Return the normalized occurred at of webhook/email/SMS."""
        timestamp = data.get("date")
        return datetime.fromtimestamp(int(timestamp)) if timestamp else None
        

    #########################################################
    # Initialization / API clients
    #########################################################

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Return the normalized event of webhook/email/SMS."""
        if "event" in data:
            return self.events_association.get(data.get("event"), "unknown")
        if "statut" in data:
            return self.events_association.get(data.get("statut"), "unknown")
        if "success" in data:
            return "sent" if data.get("success") else "failed"
        return "unknown"

    def send_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Send SMS."""
        data = {
            'apiKey': self._get_config_or_env("SMS_API_KEY"),
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
        print("---- data", data)
        response = self._request(self._api_base_sms + "/send", "POST", data)
        return response

    def status_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Status SMS."""
        responses = []
        for rp in kwargs.get("recipients", []):
            data = {
                "apiKey": self._get_config_or_env("SMS_API_KEY"),
                "messageId": kwargs.get("external_id"),
                "phoneNumber": str(rp.get("phone")),
            }
            response = self._request(self._api_base_sms + "/message-status", "GET", data)
            responses.append(response)
        return responses

    # {"status":"delivered","msgId":"95415616","date":1771941463,"phone":"+33614397083","cost":"0.049","currency":"EUR"}
    def handle_webhook_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload.decode("utf-8")
        return json.loads(payload)

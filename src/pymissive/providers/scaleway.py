"""Scaleway Transactional Email provider."""

import base64
import os
from typing import Any

import requests

from .base import MissiveProviderBase


class ScalewayProvider(MissiveProviderBase):
    name = "scaleway"
    display_name = "Scaleway"
    description = "Scaleway messaging and communication services"
    required_packages = ["requests"]
    documentation_url = "https://www.scaleway.com/en/docs/managed-services/transactional-email/"
    site_url = "https://www.scaleway.com"
    config_keys = ["SECRET_ACCESS_KEY", "REGION", "PROJECT_ID", "BASE_URL", "WEBHOOK_ID"]
    config_defaults = {
        "BASE_URL": "https://api.scaleway.com/transactional-email/v1alpha1",
        "REGION": "fr-par",
        "WEBHOOK_ID": "default",
    }
    sns_arn = "arn:scw:sns:fr-par:project-44bec53a-54d5-4f98-b183-14ba9f5f33f9:missive-webhook-email"

    ENDPOINTS = {
        "emails": "emails",
        "email_detail": "emails/{email_id}",
        "webhooks": "webhooks",
        "webhook_detail": "webhooks/{webhook_id}",
        "webhook_events": "webhooks/{webhook_id}/events",
        "subscriptions": "subscriptions",
    }

    events = {
        "unknown_type": "unknown_type",
        "email_queued": "email_queued",
        "email_dropped": "email_dropped",
        "email_deferred": "email_deferred",
        "email_delivered": "email_delivered",
        "email_spam": "email_spam",
        "email_mailbox_not_found": "email_mailbox_not_found",
        "email_blocklisted": "email_blocklisted",
        "blocklist_created": "blocklist_created",
    }

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self._base_url = self._get_config_or_env("BASE_URL", "https://api.scaleway.com/transactional-email/v1alpha1")
        self._secret_key = self._get_config_or_env("SECRET_ACCESS_KEY")
        self._region = self._get_config_or_env("REGION", "fr-par")
        self._project_id = self._get_config_or_env("PROJECT_ID")
        self._email_data: dict[str, Any] = {}

    def _get_headers(self) -> dict[str, str]:
        """Generate standard headers."""
        return {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }

    def _build_url(self, endpoint_key: str, **params) -> str:
        """Build URL from endpoint key."""
        endpoint = self.ENDPOINTS[endpoint_key].format(**params)
        return f"{self._base_url}/regions/{self._region}/{endpoint}"

    @property
    def api_url(self) -> str:
        """Return emails API URL."""
        return self._build_url("emails")

    def prepare_email(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare email data."""
        recipient_email = kwargs.get("recipient_email")
        recipient_name = kwargs.get("recipient_name")
        sender_email = kwargs.get("sender_email")
        sender_name = kwargs.get("sender_name")
        subject = kwargs.get("subject")
        body = kwargs.get("body")
        body_text = kwargs.get("body_text")

        if not recipient_email:
            raise ValueError("recipient_email is required")
        if not sender_email:
            raise ValueError("sender_email is required")
        if not self._project_id:
            raise ValueError("PROJECT_ID is required")

        if not hasattr(self, "attachments"):
            self.attachments = []

        attachments_from_kwargs = kwargs.get("attachments")
        if attachments_from_kwargs:
            for att in attachments_from_kwargs:
                if isinstance(att, dict) and "content" in att and "name" in att:
                    self.attachments.append(att)

        self._email_data = {
            "subject": subject or "",
            "from": {
                "email": sender_email,
                "name": sender_name or "",
            },
            "to": [
                {
                    "email": recipient_email,
                    "name": recipient_name or "",
                }
            ],
            "project_id": self._project_id,
        }

        if body:
            self._email_data["html"] = body
        if body_text:
            self._email_data["text"] = body_text
        
        if "html" not in self._email_data and "text" not in self._email_data:
            self._email_data["text"] = ""

        reply_to = kwargs.get("reply_to")
        if reply_to:
            self._email_data["additional_headers"] = [
                {"key": "Reply-To", "value": reply_to}
            ]

        if self.attachments:
            self._email_data["attachments"] = [
                {
                    "content": base64.b64encode(att["content"]).decode("utf-8") if isinstance(att["content"], bytes) else att["content"],
                    "name": att["name"],
                }
                for att in self.attachments
            ]

        return self._email_data

    def add_attachment_email(self, content: bytes | str, name: str) -> None:
        """Add an attachment to the email."""
        if not hasattr(self, "attachments"):
            self.attachments = []

        if isinstance(content, str):
            content = content.encode("utf-8")

        self.attachments.append({"content": content, "name": os.path.basename(name)})

        if self._email_data:
            if "attachments" not in self._email_data:
                self._email_data["attachments"] = []
            self._email_data["attachments"].append({
                "content": base64.b64encode(content).decode("utf-8"),
                "name": os.path.basename(name),
            })

    def remove_attachment_email(self, name: str) -> None:
        """Remove an attachment from the email."""
        if not hasattr(self, "attachments"):
            return

        self.attachments = [att for att in self.attachments if att["name"] != name]

        if self._email_data and "attachments" in self._email_data:
            self._email_data["attachments"] = [
                att for att in self._email_data["attachments"] if att["name"] != name
            ]

    def send_email(self, **kwargs: Any) -> bool:
        """Send email via Scaleway."""
        self.prepare_email(**kwargs)

        response = requests.post(
            self._build_url("emails"),
            headers=self._get_headers(),
            json=self._email_data,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def status_email(self, **kwargs: Any) -> dict[str, Any]:
        """Check email delivery status."""
        external_id = kwargs.get("external_id")
        
        response = requests.get(
            self._build_url("email_detail", email_id=external_id),
            headers=self._get_headers(),
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        scaleway_status = result.get("status", "unknown").lower()
        association = self.get_status_events_association()
        status = association.get(scaleway_status, "Pending")
        return status, response

    def cancel_email(self) -> bool:
        """Cancel email (not supported)."""
        return False

    def get_external_id_email(self, response: dict[str, Any]) -> str:
        """Get external email ID."""
        return response.get("emails")[0].get("id")

    def set_webhook_email(self, webhook_url: str, **kwargs) -> dict[str, Any]:
        """Create webhook (requires domain_id and sns_arn from Topics and Events)."""

    
        event_types = kwargs.get("event_types", [
            "email_delivered",
            "email_dropped",
            "email_deferred",
            "email_spam",
            "email_mailbox_not_found",
        ])
        
        data = {
            "domain_id": self._domain_id,
            "project_id": self._project_id,
            "name": kwargs.get("name", "Missive Webhook"),
            "event_types": event_types,
            "sns_arn": self.sns_arn,
        }
        
        response = requests.post(
            self._build_url("webhooks"),
            headers=self._get_headers(),
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def get_webhooks_email(self) -> dict[str, Any]:
        """Get all webhooks."""
        response = requests.get(
            self._build_url("webhooks"),
            headers=self._get_headers(),
        )
        response.raise_for_status()
        response = response.json()
        return response.get("webhooks", [])

    def delete_webhook_email(self, webhook_id: str) -> bool:
        """Delete webhook."""
        response = requests.delete(
            self._build_url("webhook_detail", webhook_id=webhook_id),
            headers=self._get_headers(),
        )
        response.raise_for_status()
        return response.json()

    def get_webhooks(self) -> dict[str, Any]:
        """Get all webhooks."""
        webhooks = []
        webhooks.extend(self.get_webhooks_email())
        return webhooks

    def get_webhook_events_email(self, webhook_id: str, **kwargs) -> list[dict[str, Any]]:
        """Get webhook events."""
        params = {}
        if "page" in kwargs:
            params["page"] = kwargs["page"]
        if "page_size" in kwargs:
            params["page_size"] = kwargs["page_size"]
        if "order_by" in kwargs:
            params["order_by"] = kwargs["order_by"]
        
        response = requests.get(
            self._build_url("webhook_events", webhook_id=webhook_id),
            headers=self._get_headers(),
            params=params,
        )
        response.raise_for_status()
        response = response.json()
        return response.get("events", [])

    def update_webhook_email(self, webhook_id: str, **kwargs) -> bool:
        """Update webhook."""
        data = {}
        if "name" in kwargs:
            data["name"] = kwargs["name"]
        if "event_types" in kwargs:
            data["event_types"] = kwargs["event_types"]
        if "sns_arn" in kwargs:
            data["sns_arn"] = kwargs["sns_arn"]
        
        response = requests.patch(
            self._build_url("webhook_detail", webhook_id=webhook_id),
            headers=self._get_headers(),
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def handle_webhook_email(self, payload: dict[str, Any]) -> bool:
        """Handle webhook."""
        return True
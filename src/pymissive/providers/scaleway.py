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

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Scaleway provider."""
        super().__init__(**kwargs)
        self._base_url = self._get_config_or_env("BASE_URL", "https://api.scaleway.com/transactional-email/v1alpha1")
        self._secret_key = self._get_config_or_env("SECRET_ACCESS_KEY")
        self._region = self._get_config_or_env("REGION", "fr-par")
        self._project_id = self._get_config_or_env("PROJECT_ID")
        self._email_data: dict[str, Any] = {}

    @property
    def api_url(self) -> str:
        """Return the API URL for the region."""
        return f"{self._base_url}/regions/{self._region}/emails"

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

        # Initialize attachments if not already done
        if not hasattr(self, "attachments"):
            self.attachments = []

        # Add attachments from kwargs if provided
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

        # Scaleway requires at least html or text content
        if body:
            self._email_data["html"] = body
        if body_text:
            self._email_data["text"] = body_text
        
        # If neither html nor text is provided, use empty text as fallback
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

        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }

        response = requests.post(
            self.api_url,
            headers=headers,
            json=self._email_data,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def status_email(self, **kwargs: Any) -> dict[str, Any]:
        """Check email delivery status."""
        external_id = kwargs.get("external_id")
        status_url = f"{self._base_url}/regions/{self._region}/emails/{external_id}"
        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }
        response = requests.get(
            status_url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        status_mapping = {
            "pending": "pending",
            "sent": "sent",
            "delivered": "delivered",
            "opened": "delivered",  # Opened is considered delivered
            "clicked": "delivered",  # Clicked is considered delivered
            "bounced": "failed",
            "failed": "failed",
            "rejected": "failed",
        }
        status = status_mapping.get(scaleway_status.lower(), "unknown")
        return status, response

    def cancel_email(self) -> bool:
        """Cancel email sending (not supported by Scaleway)."""
        return False

    def get_external_id_email(self, response: dict[str, Any]) -> str:
        """Get the external ID of the email."""
        return response.get("emails")[0].get("id")

    def set_webhook(self, webhook_url: str) -> bool:
        """Set a webhook for Scaleway."""
        webhook_url = f"https://api.scaleway.com/transactional-email/v1alpha1/regions/{self._region}/webhooks"  
        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }
        response = requests.post(
            webhook_url,
            headers=headers,
            json={"url": webhook_url},
        )
        response.raise_for_status()
        return response.json()

    def delete_webhook(self) -> bool:
        """Delete a webhook for Scaleway."""
        webhook_url = f"https://api.scaleway.com/transactional-email/v1alpha1/regions/{self._region}/webhooks/{self._webhook_id}"
        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }
        response = requests.delete(webhook_url, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_webhooks(self) -> dict[str, Any]:
        """Get a webhook for Scaleway."""
        webhook_url = f"https://api.scaleway.com/transactional-email/v1alpha1/regions/{self._region}/webhooks"
        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }
        response = requests.get(webhook_url, headers=headers)
        response.raise_for_status()
        return response.json()

    def update_webhook(self, webhook_id: str, webhook_url: str) -> bool:
        """Update a webhook for Scaleway."""
        webhook_url = f"https://api.scaleway.com/transactional-email/v1alpha1/regions/{self._region}/webhooks/{webhook_id}"
        headers = {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }
        response = requests.put(webhook_url, headers=headers, json={"url": webhook_url})
        response.raise_for_status()
        return response.json()

    def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle a Scaleway webhook."""
        print("Scaleway webhook received")
        return True
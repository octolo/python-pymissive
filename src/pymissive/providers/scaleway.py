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
    config_keys = ["SECRET_KEY", "REGION", "PROJECT_ID", "BASE_URL"]
    config_defaults = {
        "BASE_URL": "https://api.scaleway.com/transactional-email/v1alpha1",
        "REGION": "fr-par",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Scaleway provider."""
        super().__init__(**kwargs)
        self._base_url = self._get_config_or_env("BASE_URL", "https://api.scaleway.com/transactional-email/v1alpha1")
        self._secret_key = self._get_config_or_env("SECRET_KEY")
        self._region = self._get_config_or_env("REGION", "fr-par")
        self._project_id = self._get_config_or_env("PROJECT_ID")
        self._email_data: dict[str, Any] = {}

    @property
    def api_url(self) -> str:
        """Retourne l'URL de l'API pour la région."""
        return f"{self._base_url}/regions/{self._region}/emails"

    def prepare_email(self) -> dict[str, Any]:
        """Prépare les données de l'email."""
        recipient_email = self._get_missive_value("recipient_email")
        recipient_name = self._get_missive_value("recipient_name")
        sender_email = self._get_missive_value("sender_email")
        sender_name = self._get_missive_value("sender_name")
        subject = self._get_missive_value("subject")
        body = self._get_missive_value("body")
        body_text = self._get_missive_value("body_text")

        if not recipient_email:
            raise ValueError("recipient_email is required")
        if not sender_email:
            raise ValueError("sender_email is required")
        if not self._project_id:
            raise ValueError("PROJECT_ID is required")

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

        reply_to = self._get_missive_value("reply_to")
        if reply_to:
            self._email_data["additional_headers"] = [
                {"key": "Reply-To", "value": reply_to}
            ]

        if not hasattr(self, "attachments"):
            self.attachments = []

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
        """Ajoute une pièce jointe à l'email."""
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
        """Retire une pièce jointe de l'email."""
        if not hasattr(self, "attachments"):
            return

        self.attachments = [att for att in self.attachments if att["name"] != name]

        if self._email_data and "attachments" in self._email_data:
            self._email_data["attachments"] = [
                att for att in self._email_data["attachments"] if att["name"] != name
            ]

    def send_email(self) -> bool:
        """Envoie l'email via Scaleway."""
        if not self._secret_key:
            self._update_status(
                self.MissiveStatus.FAILED if hasattr(self, "MissiveStatus") else "FAILED",
                error_message="SCALEWAY_SECRET_KEY is required"
            )
            return False

        if not self._project_id:
            self._update_status(
                self.MissiveStatus.FAILED if hasattr(self, "MissiveStatus") else "FAILED",
                error_message="SCALEWAY_PROJECT_ID is required"
            )
            return False

        try:
            self.prepare_email()

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

            result = response.json()
            message_id = result.get("id") or result.get("message_id")

            self._update_status(
                self.MissiveStatus.SENT if hasattr(self, "MissiveStatus") else "SENT",
                provider=self.name,
                external_id=str(message_id) if message_id else None
            )
            return True

        except requests.exceptions.RequestException as e:
            self._update_status(
                self.MissiveStatus.FAILED if hasattr(self, "MissiveStatus") else "FAILED",
                error_message=f"Scaleway API error: {str(e)}"
            )
            return False

    def cancel_email(self) -> bool:
        """Annule l'envoi d'un email (non supporté par Scaleway)."""
        return False
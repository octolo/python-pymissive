"""Telegram Bot API provider."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class TelegramProvider(BaseProvider):
    """Telegram provider."""

    name = "telegram"
    display_name = "Telegram"
    supported_types = ["BRANDED"]
    brands = ["telegram"]
    config_keys = ["TELEGRAM_BOT_TOKEN"]
    required_packages = ["python-telegram-bot"]
    site_url = "https://telegram.org/"
    description_text = "Secure instant messaging with bots"
    # Geographic scope
    branded_geo = "*"

    def validate(self) -> tuple[bool, str]:
        """Validates recipient has Telegram chat_id."""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient:
            return False, "Recipient not defined"

        metadata = getattr(recipient, "metadata", None) or {}
        chat_id = metadata.get("telegram_chat_id")
        if not chat_id:
            return False, "Recipient has no telegram_chat_id in metadata"

        return True, ""

    def send_branded(self, brand_name: Optional[str] = None, **kwargs) -> bool:
        """Sends message via Telegram Bot API."""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        # For now, simulate sending
        external_id = f"telegram_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """
        Check status of a Telegram message.

        Note: Telegram does not provide automatic webhooks for delivery status.
        Can only know if message was sent.
        """
        # TODO: Implement if needed
        return None


__all__ = ["TelegramProvider"]

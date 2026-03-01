"""Facebook Messenger provider."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class MessengerProvider(BaseProvider):
    """
    Facebook Messenger provider.

    Required configuration:
        MESSENGER_PAGE_ACCESS_TOKEN: Facebook page access token
        MESSENGER_APP_SECRET: Application secret

    Recipient must have a PSID (Page-Scoped ID) Messenger stored in metadata.
    """

    name = "messenger"
    display_name = "Facebook Messenger"
    supported_types = ["BRANDED"]
    brands = ["messenger"]  # Facebook Messenger only
    config_keys = ["MESSENGER_PAGE_ACCESS_TOKEN", "MESSENGER_VERIFY_TOKEN"]
    required_packages = ["requests"]
    site_url = "https://www.messenger.com/"
    description_text = "Facebook Messenger - Consumer instant messaging (Meta)"

    def validate(self) -> tuple[bool, str]:
        """Validate that the recipient has a Messenger PSID"""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient:
            return False, "Recipient not defined"

        metadata = getattr(recipient, "metadata", None) or {}
        psid = metadata.get("messenger_psid")
        if not psid:
            return False, "Recipient does not have a Messenger PSID (add to metadata)"

        return True, ""

    def send_branded(self, brand_name: Optional[str] = None, **kwargs) -> bool:
        """
        Send a message via Messenger Send API.

        TODO: Implement actual sending via:
        POST https://graph.facebook.com/v18.0/me/messages
        """
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        external_id = f"messenger_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """Check status via Messenger webhooks"""
        # TODO: Implement webhook handlers
        return None


__all__ = ["MessengerProvider"]

"""Signal Messenger provider."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class SignalProvider(BaseProvider):
    """
    Signal Messenger provider.

    Required configuration:
        SIGNAL_CLI_REST_API_URL: signal-cli-rest-api URL
        SIGNAL_SENDER_NUMBER: Registered sender number

    Recipient must have a mobile phone number.
    """

    name = "signal"
    display_name = "Signal"
    supported_types = ["BRANDED"]
    brands = ["signal"]  # Signal only
    config_keys = ["SIGNAL_API_KEY"]
    required_packages = ["requests"]
    site_url = "https://signal.org/"
    description_text = "Secure end-to-end encrypted messaging"

    def validate(self) -> tuple[bool, str]:
        """Validate that the recipient has a mobile number"""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient or not getattr(recipient, "mobile", None):
            return False, "Recipient must have a mobile number for Signal"

        return True, ""

    def send_branded(self, brand_name: Optional[str] = None, **kwargs) -> bool:
        """
        Send a message via Signal.

        TODO: Implement actual sending via signal-cli-rest-api
        """
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        external_id = f"signal_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """Check status of a Signal message"""
        # TODO: Implement if needed
        return None


__all__ = ["SignalProvider"]

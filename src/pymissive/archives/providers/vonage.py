"""Vonage provider for SMS and Voice."""

from __future__ import annotations

from typing import Dict

from ..status import MissiveStatus
from .base import BaseProvider


class VonageProvider(BaseProvider):
    """
    Vonage (ex-Nexmo) provider.

    Required configuration:
        VONAGE_API_KEY: Vonage API key
        VONAGE_API_SECRET: Vonage API secret
        VONAGE_FROM_NUMBER: Sender number

    Supports:
    - SMS
    - Voice (voice calls)
    - Verify (2FA verification)
    """

    name = "vonage"
    display_name = "Vonage"
    supported_types = ["SMS", "VOICE_CALL"]
    services = ["sms", "voice", "verify", "number_insight"]
    config_keys = ["VONAGE_API_KEY", "VONAGE_API_SECRET", "VONAGE_FROM_NUMBER"]
    required_packages = ["vonage"]
    site_url = "https://www.vonage.com/"
    status_url = "https://vonage.statuspage.io/"
    documentation_url = "https://developer.vonage.com/"
    description_text = "Global SMS and Voice platform (formerly Nexmo)"

    def send_sms(self, **kwargs) -> bool:
        """Send an SMS via Vonage API"""
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_phone"):
            self._update_status(MissiveStatus.FAILED, error_message="Phone missing")
            return False

        try:
            # TODO: Implement actual Vonage SMS sending
            # from vonage import Client, Sms
            #
            # api_key = self._config.get("VONAGE_API_KEY")
            # api_secret = self._config.get("VONAGE_API_SECRET")
            # from_number = self._config.get("VONAGE_FROM_NUMBER")
            #
            # if not all([api_key, api_secret, from_number]):
            #     self._update_status(
            #         MissiveStatus.FAILED,
            #         error_message="Incomplete Vonage configuration",
            #     )
            #     return False
            #
            # client = Client(key=api_key, secret=api_secret)
            # sms = Sms(client)
            #
            # message_params = {
            #     "from": kwargs.get("sender", from_number),
            #     "to": self.missive.recipient_phone,
            #     "text": self.missive.body_text or self.missive.body,
            # }
            #
            # if self.missive.id:
            #     message_params["client-ref"] = f"missive_{self.missive.id}"
            #
            # response = sms.send_message(message_params)
            #
            # if response["messages"][0]["status"] == "0":
            #     message_id = response["messages"][0]["message-id"]
            #     self._update_status(
            #         MissiveStatus.SENT,
            #         provider=self.name,
            #         external_id=message_id,
            #     )
            #     self._create_event("sent", f"SMS sent via Vonage (ID: {message_id})")
            #     return True
            # else:
            #     error_code = response["messages"][0]["status"]
            #     error_text = response["messages"][0].get("error-text", "Unknown error")
            #     self._update_status(
            #         MissiveStatus.FAILED,
            #         error_message=f"Vonage error {error_code}: {error_text}",
            #     )
            #     return False

            # Simulation
            external_id = f"vonage_sms_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=external_id,
            )
            self._create_event("sent", "SMS sent via Vonage")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def send_voice_call(self, **kwargs) -> bool:
        """Send a voice call via Vonage API"""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_phone"):
            self._update_status(MissiveStatus.FAILED, error_message="Phone missing")
            return False

        try:
            # TODO: Implement actual Vonage Voice call
            # from vonage import Client, Voice
            #
            # api_key = self._config.get("VONAGE_API_KEY")
            # api_secret = self._config.get("VONAGE_API_SECRET")
            #
            # client = Client(key=api_key, secret=api_secret)
            # voice = Voice(client)
            #
            # response = voice.create_call({
            #     "to": [{"type": "phone", "number": self.missive.recipient_phone}],
            #     "from": {"type": "phone", "number": self._config.get("VONAGE_FROM_NUMBER")},
            #     "ncco": [{"action": "talk", "text": self.missive.body}]
            # })
            #
            # external_id = response["uuid"]

            # Simulation
            external_id = f"vonage_voice_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=external_id,
            )
            self._create_event("sent", "Voice call initiated via Vonage")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def get_sms_service_info(self) -> Dict:
        """
        Gets Vonage service information.

        Returns:
            Dict with balance, limits, etc.
        """
        try:
            api_key = self._config.get("VONAGE_API_KEY")
            api_secret = self._config.get("VONAGE_API_SECRET")

            if not all([api_key, api_secret]):
                return {
                    "credits": None,
                    "credits_type": "amount",
                    "is_available": False,
                    "limits": {},
                    "warnings": ["Incomplete Vonage configuration"],
                    "details": {},
                }

            # TODO: Implement actual Vonage API call
            # from vonage import Client
            #
            # client = Client(key=api_key, secret=api_secret)
            # balance = client.get_balance()
            # balance_value = float(balance.get("value", 0))
            # currency = "EUR"

            return {
                "credits": None,
                "credits_type": "amount",
                "is_available": None,
                "limits": {},
                "warnings": ["Vonage API not implemented - uncomment the code"],
                "details": {},
            }

        except Exception as e:
            return {
                "credits": None,
                "credits_type": "amount",
                "is_available": False,
                "limits": {},
                "warnings": [f"Error: {str(e)}"],
                "details": {},
            }


__all__ = ["VonageProvider"]

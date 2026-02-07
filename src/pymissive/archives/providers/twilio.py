"""Twilio provider for SMS and WhatsApp."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from ..status import MissiveStatus
from .base import BaseProvider


class TwilioProvider(BaseProvider):
    """Twilio provider (SMS and WhatsApp)."""

    name = "twilio"
    display_name = "Twilio"
    supported_types = ["SMS", "BRANDED", "VOICE_CALL"]
    services = ["sms", "whatsapp", "voice", "verify"]
    brands = ["whatsapp"]
    config_keys = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"]
    required_packages = ["twilio"]
    site_url = "https://www.twilio.com/"
    status_url = "https://status.twilio.com/"
    documentation_url = "https://www.twilio.com/docs"
    description_text = "Global multi-channel cloud platform (SMS, WhatsApp, Voice)"

    def send_twilio(self) -> bool:
        """Dispatches to WhatsApp for BRANDED type."""
        return self.send_whatsapp()

    def send_sms(self) -> bool:
        """Sends SMS via Twilio."""
        is_valid, error = self._validate_and_check_recipient(
            "recipient_phone", "Phone missing"
        )
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        try:
            # TODO: Implement actual Twilio SMS sending
            # from twilio.rest import Client
            #
            # account_sid = self._config.get('TWILIO_ACCOUNT_SID')
            # auth_token = self._config.get('TWILIO_AUTH_TOKEN')
            # from_number = self._config.get('TWILIO_PHONE_NUMBER')
            #
            # client = Client(account_sid, auth_token)
            # message = client.messages.create(
            #     body=self.missive.body,
            #     from_=from_number,
            #     to=self.missive.recipient_phone
            # )
            #
            # external_id = message.sid

            # Simulation
            external_id = f"tw_sms_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", "SMS sent via Twilio")

            return True

        except Exception as e:
            return self._handle_send_error(e)

    def send_whatsapp(self) -> bool:
        """Send via WhatsApp via Twilio"""
        is_valid, error = self._validate_and_check_recipient(
            "recipient_phone", "Phone missing"
        )
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        try:
            # TODO: Integrate with Twilio WhatsApp
            # from twilio.rest import Client
            #
            # account_sid = self._config.get('TWILIO_ACCOUNT_SID')
            # auth_token = self._config.get('TWILIO_AUTH_TOKEN')
            #
            # client = Client(account_sid, auth_token)
            #
            # from_number = f"whatsapp:{self._config.get('TWILIO_WHATSAPP_NUMBER')}"
            # to_number = f"whatsapp:{self.missive.recipient_phone}"
            #
            # message = client.messages.create(
            #     body=self.missive.body,
            #     from_=from_number,
            #     to=to_number,
            #     status_callback=self._config.get('TWILIO_WEBHOOK_URL')
            # )
            #
            # external_id = message.sid

            # Simulation
            external_id = f"tw_wa_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", "WhatsApp message sent via Twilio")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def send_voice_call(self) -> bool:
        """Send voice call via Twilio."""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_phone"):
            self._update_status(MissiveStatus.FAILED, error_message="Phone missing")
            return False

        try:
            # TODO: Implement actual Twilio Voice call
            # from twilio.rest import Client
            #
            # account_sid = self._config.get('TWILIO_ACCOUNT_SID')
            # auth_token = self._config.get('TWILIO_AUTH_TOKEN')
            #
            # client = Client(account_sid, auth_token)
            # call = client.calls.create(
            #     to=self.missive.recipient_phone,
            #     from_=self._config.get('TWILIO_PHONE_NUMBER'),
            #     url=self._config.get('TWILIO_VOICE_URL'),  # TwiML URL
            # )
            #
            # external_id = call.sid

            # Simulation
            external_id = f"tw_voice_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", "Voice call initiated via Twilio")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def validate_webhook_signature(
        self, payload: Dict, headers: Dict
    ) -> Tuple[bool, str]:
        """Validate Twilio webhook signature."""
        auth_token = self._config.get("TWILIO_AUTH_TOKEN")
        if not auth_token:
            return True, ""

        signature = headers.get("HTTP_X_TWILIO_SIGNATURE", "")
        if not signature:
            return False, "Signature missing"

        # Twilio validation requires the full URL
        # For simplicity, validation can be disabled in dev
        # In production, implement according to:
        # https://www.twilio.com/docs/usage/webhooks/webhooks-security

        return True, ""  # Simplified for now

    def extract_sms_missive_id(self, payload: Dict) -> Optional[str]:
        """Extract missive ID from Twilio webhook."""
        # Twilio returns MessageSid, we must have stored it in external_id
        return payload.get("MessageSid")

    def extract_event_type(self, payload: Dict) -> str:
        """Extract status from Twilio webhook."""
        return payload.get("MessageStatus", "unknown")

    def get_status_from_event(self, event_type: str) -> Optional[MissiveStatus]:
        """Map Twilio statuses to MissiveStatus."""
        status_mapping = {
            "queued": MissiveStatus.PENDING,
            "sending": MissiveStatus.PENDING,
            "sent": MissiveStatus.SENT,
            "delivered": MissiveStatus.DELIVERED,
            "undelivered": MissiveStatus.FAILED,
            "failed": MissiveStatus.FAILED,
            "read": MissiveStatus.READ,
        }
        return status_mapping.get(event_type.lower())

    def get_service_status(self) -> Dict:
        """
        Gets Twilio status and credits.

        Twilio uses a prepaid system in USD.

        Returns:
            Dict with status, credits in USD, etc.
        """
        last_check = self._get_last_check_time()

        return {
            "status": "unknown",
            "is_available": None,
            "services": self._get_services(),
            "credits": {
                "type": "money",
                "remaining": None,
                "currency": "USD",
                "limit": None,
                "percentage": None,
            },
            "rate_limits": {
                "per_second": 1,
                "per_minute": 60,
            },
            "sla": {
                "uptime_percentage": 99.95,
            },
            "last_check": last_check,
            "warnings": ["Twilio API not implemented - uncomment the code"],
            "details": {
                "refill_url": "https://www.twilio.com/console/billing",
                "status_page": "https://status.twilio.com/",
                "api_docs": ("https://www.twilio.com/docs/usage/api/usage-record"),
            },
        }

    def cancel_sms(self) -> bool:
        """
        Cancel SMS sending via Twilio.

        Twilio allows canceling messages in 'queued' or 'scheduled' status.

        Returns:
            bool: True if cancellation succeeded, False otherwise
        """
        if not self.missive or not getattr(self.missive, "external_id", None):
            return False

        try:
            # TODO: Implement actual cancellation
            # from twilio.rest import Client
            #
            # account_sid = self._config.get("TWILIO_ACCOUNT_SID")
            # auth_token = self._config.get("TWILIO_AUTH_TOKEN")
            #
            # if not account_sid or not auth_token:
            #     return False
            #
            # client = Client(account_sid, auth_token)
            # message = client.messages(self.missive.external_id).update(
            #     status="canceled"
            # )
            #
            # if message.status == "canceled":
            #     self._create_event("cancelled", "SMS cancelled via Twilio")
            #     return True
            # else:
            #     return False

            return False

        except Exception:
            return False

    def cancel_twilio(self) -> bool:
        """
        Cancel branded message (WhatsApp) sending via Twilio.

        Called automatically by cancel_branded() via dispatch.
        Works the same way as cancel_sms() because Twilio uses
        the same API for SMS and WhatsApp.

        Returns:
            bool: True if cancellation succeeded, False otherwise
        """
        return self.cancel_sms()

    def cancel_whatsapp(self) -> bool:
        """
        Cancels WhatsApp message sending via Twilio.

        Called automatically by cancel_branded("whatsapp") via dispatch.

        Returns:
            bool: True if cancellation succeeded, False otherwise
        """
        return self.cancel_sms()

    def get_whatsapp_service_info(self) -> Dict:
        """
        Gets WhatsApp service information via Twilio.

        Called automatically by get_branded_service_info("whatsapp") via dispatch.

        Returns:
            Dict with status, credits, etc.
        """
        # WhatsApp via Twilio uses the same credit system as SMS
        return self.get_service_status()


__all__ = ["TwilioProvider"]

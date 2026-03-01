"""Voice call provider mixin without Django dependencies."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ...status import MissiveStatus


class BaseVoiceCallMixin:
    """Voice call-specific functionality mixin."""

    voice_call_archiving_duration: int = 0  # Days call logs stay downloadable
    voice_call_geographic_coverage: list[str] | str = ["*"]
    voice_call_geo = voice_call_geographic_coverage

    def get_voice_call_service_info(self) -> Dict[str, Any]:
        """Return voice call service information. Override in subclasses."""
        return {
            "credits": None,
            "credits_type": "time",
            "is_available": None,
            "limits": {
                "archiving_duration_days": self.voice_call_archiving_duration,
            },
            "warnings": [
                "get_voice_call_service_info() method not implemented for this provider"
            ],
            "options": [],
            "details": {
                "geographic_coverage": self.voice_call_geographic_coverage,
            },
        }

    def check_voice_call_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check voice call delivery status. Override in subclasses."""
        return {
            "status": "unknown",
            "delivered_at": None,
            "duration": None,
            "error_code": None,
            "error_message": "check_voice_call_delivery_status() method not implemented for this provider",
            "details": {},
        }

    def send_voice_call(self, **kwargs) -> bool:
        """Send a voice call. Override in subclasses."""
        recipient_phone = self._get_missive_value("get_recipient_phone")
        if not recipient_phone:
            recipient_phone = self._get_missive_value("recipient_phone")

        if not recipient_phone:
            self._update_status(MissiveStatus.FAILED, error_message="No phone number")
            return False

        raise NotImplementedError(
            f"{self.name} must implement the send_voice_call() method"
        )

    def cancel_voice_call(self, **kwargs) -> bool:
        """Cancel a scheduled voice call (override in subclasses)."""
        return False

    def validate_voice_call_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate voice call webhook signature. Override in subclasses."""
        return True, ""

    def handle_voice_call_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process voice call webhook payload. Override in subclasses."""
        return (
            False,
            "handle_voice_call_webhook() method not implemented for this provider",
            None,
        )

    def extract_voice_call_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extract missive ID from voice call webhook payload. Override in subclasses."""
        return None

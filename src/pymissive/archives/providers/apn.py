"""Apple Push Notification provider."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..status import MissiveStatus
from .base import BaseProvider


class APNProvider(BaseProvider):
    """
    Apple Push Notification Service provider.

    Required configuration:
        APN_CERTIFICATE_PATH
        APN_KEY_ID
        APN_TEAM_ID
        APN_BUNDLE_ID
        APN_USE_SANDBOX

    The missive recipient must expose an `apn_device_token` in its metadata.
    """

    name = "apn"
    display_name = "Apple Push Notification"
    supported_types = ["PUSH_NOTIFICATION"]
    # Geographic scope
    push_notification_geo = "*"
    config_keys = ["APN_CERTIFICATE_PATH", "APN_KEY_ID", "APN_TEAM_ID"]
    required_packages = ["aioapns"]
    site_url = "https://developer.apple.com/documentation/usernotifications"
    description_text = "Native iOS push notifications via APNs (Apple)"

    def send_push_notification(self, **kwargs) -> bool:
        """Send a push notification via APN (simulated)."""
        risk = self.calculate_push_notification_delivery_risk()
        if not risk.get("should_send", True):
            recommendations = risk.get("recommendations", [])
            error_message = next(
                (rec for rec in recommendations if rec), "Push notification blocked"
            )
            self._update_status(
                MissiveStatus.FAILED,
                error_message=error_message,
            )
            return False

        simulated_external_id = f"apn_sim_{self._get_missive_value('id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=simulated_external_id,
        )

        return True

    def cancel_push_notification(self, **kwargs) -> bool:
        """Cancel a push notification (APN doesn't support cancellation)."""
        return False

    def check_push_notification_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check APN delivery status (not available by default)."""
        external_id = kwargs.get("external_id") or self._get_missive_value(
            "external_id"
        )
        return {
            "status": "unknown",
            "delivered_at": None,
            "read_at": None,
            "error_code": None,
            "error_message": "APN doesn't provide delivery confirmation by default",
            "details": {
                "external_id": external_id,
                "provider": "apn",
            },
        }

    def get_push_notification_service_info(self) -> Dict[str, Any]:
        """Return push notification service information for APN."""
        return {
            "credits": None,
            "credits_type": "unlimited",
            "is_available": True,
            "limits": {},
            "warnings": [],
            "channels": ["ios"],
            "details": {
                "platform": "ios",
                "supports_fcm": False,
                "provider": "apn",
            },
        }

    def calculate_push_notification_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Calculate delivery risk for push notification."""

        def _handler(
            target_missive: Any,
            factors: Dict[str, Any],
            recommendations: List[str],
            total_risk: float,
        ) -> Dict[str, Any]:
            recipient = getattr(target_missive, "recipient", None)
            risk_total = total_risk
            if not recipient:
                recommendations.append("Recipient not defined")
                risk_total = 100.0
            else:
                metadata = getattr(recipient, "metadata", {}) or {}
                device_token = metadata.get("apn_device_token")
                if not device_token:
                    recommendations.append("Missing APN device token")
                    risk_total = 100.0
                else:
                    factors["device_token_present"] = True
                    factors["device_token_length"] = len(device_token)
                    if len(device_token) != 64:
                        recommendations.append(
                            "Device token format is invalid (expected 64 characters)"
                        )
                        risk_total = max(risk_total, 90)

            service_check = self.check_service_availability()
            factors["service_availability"] = service_check
            if service_check.get("is_available") is False:
                risk_total += 20
                recommendations.append("Service temporarily unavailable")

            risk_score = min(int(risk_total), 100)
            risk_level = self._calculate_risk_level(risk_score)
            should_send = risk_total < 70

            return {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "factors": factors,
                "recommendations": recommendations,
                "should_send": should_send,
            }

        return self._run_risk_analysis(missive, _handler)

    def handle_webhook(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process APN webhook (APN doesn't send webhooks by default)."""
        return False, "APN doesn't provide webhook notifications", None

    def validate_push_notification_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate APN webhook signature (not applicable)."""
        return True, ""

    def extract_push_notification_missive_id(self, payload: Any) -> Optional[str]:
        """Extract missive ID from APN webhook payload."""
        if isinstance(payload, dict):
            apns_id = payload.get("apns_id", "")
            if isinstance(apns_id, str) and apns_id.startswith("apn_sim_"):
                return apns_id.replace("apn_sim_", "")
        return None


__all__ = ["APNProvider"]

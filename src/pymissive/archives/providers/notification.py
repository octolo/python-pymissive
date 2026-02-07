"""In-app notification provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..status import MissiveStatus
from .base import BaseProvider


class InAppNotificationProvider(BaseProvider):
    """In-app notification provider."""

    name = "notification"
    display_name = "Notification In-App"
    supported_types = ["NOTIFICATION"]
    services = ["notification"]
    notification_geographic_coverage = ["*"]
    notification_geo = notification_geographic_coverage
    required_packages = []
    description_text = "In-app notifications without external dependency"

    def send_notification(self, **kwargs) -> bool:
        """Create an in-app notification"""
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_user"):
            self._update_status(MissiveStatus.FAILED, error_message="User missing")
            return False

        try:
            # TODO: Create the notification
            # Can use:
            # - Django signals
            # - WebSocket (channels)
            # - Firebase Cloud Messaging
            # - OneSignal
            #
            # Example with signal:
            # from django.dispatch import Signal
            # notification_created = Signal()
            # notification_created.send(
            #     sender=self.__class__,
            #     missive=self.missive,
            #     recipient=self.missive.recipient_user,
            #     subject=self.missive.subject,
            #     body=self.missive.body
            # )

            # Notification is instantaneous
            clock = getattr(self, "_clock", None)
            now = clock() if callable(clock) else datetime.now(timezone.utc)

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
            )
            # Set sent_at and delivered_at to now for instant notifications
            if self.missive and hasattr(self.missive, "sent_at"):
                self.missive.sent_at = now
            if self.missive and hasattr(self.missive, "delivered_at"):
                self.missive.delivered_at = now

            self._create_event("sent", "Notification created")
            self._create_event("delivered", "Notification delivered")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """No webhooks for in-app notifications"""
        return False, "In-app notifications do not use webhooks"

    def get_service_status(self) -> Dict:
        """
        Gets in-app notification system status.

        In-app notifications are managed locally, no limits.

        Returns:
            Dict with status, availability, etc.
        """
        return self._build_generic_service_status(
            status="operational",
            is_available=True,
            credits_type="unlimited",
            rate_limits={"per_second": None},
            sla={"uptime_percentage": 100.0},
            details={
                "provider_type": "In-App (Local)",
                "note": "Notifications stockées en base de données",
            },
        )


__all__ = ["InAppNotificationProvider"]

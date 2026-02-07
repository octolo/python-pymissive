"""Firebase Cloud Messaging provider for push notifications."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class FCMProvider(BaseProvider):
    """
    Firebase Cloud Messaging provider (push notifications).

    Required configuration:
        FCM_SERVER_KEY: Firebase server key
        or
        FCM_SERVICE_ACCOUNT_JSON: Path to service account JSON file

    Recipient must have an FCM device_token stored in metadata.
    """

    name = "fcm"
    display_name = "Firebase Cloud Messaging"
    supported_types = ["PUSH_NOTIFICATION"]
    # Geographic scope
    push_notification_geo = "*"
    config_keys = ["FCM_SERVER_KEY"]
    required_packages = ["firebase-admin"]
    site_url = "https://firebase.google.com/products/cloud-messaging"
    description_text = "Mobile push notifications for Android and iOS (Google Firebase)"

    def validate(self) -> tuple[bool, str]:
        """Validate that the recipient has an FCM device token"""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient:
            return False, "Recipient not defined"

        metadata = getattr(recipient, "metadata", None) or {}
        device_token = metadata.get("fcm_device_token")
        if not device_token:
            return (
                False,
                "Recipient does not have an FCM device token (add to metadata)",
            )

        return True, ""

    def send_push_notification(self, **kwargs) -> bool:
        """
        Send a push notification via FCM.

        TODO: Implement actual sending via firebase-admin SDK:
        from firebase_admin import messaging
        """
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        # message = messaging.Message(
        #     notification=messaging.Notification(
        #         title=self.missive.subject,
        #         body=self.missive.body_text or self.missive.body[:100],
        #     ),
        #     token=device_token,
        # )
        # response = messaging.send(message)

        external_id = f"fcm_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """
        Check delivery status.

        Note: FCM provides callbacks via webhooks.
        """
        return None


__all__ = ["FCMProvider"]

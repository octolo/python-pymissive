from .base import MissiveProviderBase


class FCMProvider(MissiveProviderBase):
    name = "fcm"
    display_name = "Firebase Cloud Messaging"
    description = "Mobile push notifications for Android and iOS (Google Firebase)"

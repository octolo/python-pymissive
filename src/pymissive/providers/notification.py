from .base import MissiveProviderBase


class NotificationProvider(MissiveProviderBase):
    name = "notification"
    display_name = "Notification In-App"
    description = "In-app notifications without external dependency"

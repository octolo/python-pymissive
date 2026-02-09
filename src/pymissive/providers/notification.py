from .base import MissiveProviderBase


class NotificationProvider(MissiveProviderBase):
    abstract = True
    name = "notification"
    display_name = "Notification In-App"
    description = "In-app notifications without external dependency"

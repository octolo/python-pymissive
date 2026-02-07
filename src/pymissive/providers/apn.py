from .base import MissiveProviderBase


class APNProvider(MissiveProviderBase):
    name = "apn"
    display_name = "Apple Push Notification"
    description = "Native iOS push notifications via APNs (Apple)"

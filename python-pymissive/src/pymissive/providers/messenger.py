from .base import MissiveProviderBase


class MessengerProvider(MissiveProviderBase):
    abstract = True
    name = "messenger"
    display_name = "Facebook Messenger"
    description = "Facebook Messenger - Consumer instant messaging (Meta)"

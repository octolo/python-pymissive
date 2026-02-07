from .base import MissiveProviderBase


class SlackProvider(MissiveProviderBase):
    name = "slack"
    display_name = "Slack"
    description = "Professional team collaboration messaging"

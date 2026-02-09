from .base import MissiveProviderBase


class SlackProvider(MissiveProviderBase):
    abstract = True
    name = "slack"
    display_name = "Slack"
    description = "Professional team collaboration messaging"

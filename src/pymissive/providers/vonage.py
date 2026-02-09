from .base import MissiveProviderBase


class VonageProvider(MissiveProviderBase):
    abstract = True
    name = "vonage"
    display_name = "Vonage"
    description = "Global SMS and Voice platform (formerly Nexmo)"

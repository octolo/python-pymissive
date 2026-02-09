from .base import MissiveProviderBase


class TwilioProvider(MissiveProviderBase):
    abstract = True
    name = "twilio"
    display_name = "Twilio"
    description = "Global multi-channel cloud platform (SMS, WhatsApp, Voice)"

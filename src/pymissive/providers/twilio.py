from .base import MissiveProviderBase


class TwilioProvider(MissiveProviderBase):
    name = "twilio"
    display_name = "Twilio"
    description = "Global multi-channel cloud platform (SMS, WhatsApp, Voice)"

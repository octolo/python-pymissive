from .base import MissiveProviderBase


class SendgridProvider(MissiveProviderBase):
    name = "SendGrid"
    display_name = "SendGrid"
    description = "Transactional and marketing email (Twilio SendGrid)"

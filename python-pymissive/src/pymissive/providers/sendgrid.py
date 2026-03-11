from .base import MissiveProviderBase


class SendgridProvider(MissiveProviderBase):
    abstract = True
    name = "SendGrid"
    display_name = "SendGrid"
    description = "Transactional and marketing email (Twilio SendGrid)"

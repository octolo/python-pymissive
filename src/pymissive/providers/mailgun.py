from .base import MissiveProviderBase


class MailgunProvider(MissiveProviderBase):
    name = "Mailgun"
    display_name = "Mailgun"
    description = "Transactional email service with advanced validation and routing"

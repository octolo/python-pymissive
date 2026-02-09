from .base import MissiveProviderBase


class MailgunProvider(MissiveProviderBase):
    abstract = True
    name = "Mailgun"
    display_name = "Mailgun"
    description = "Transactional email service with advanced validation and routing"

from .base import MissiveProviderBase


class SMTPProvider(MissiveProviderBase):
    abstract = True
    name = "smtp"
    display_name = "SMTP"
    description = "Direct SMTP integration with optional TLS/SSL and inline attachment support."

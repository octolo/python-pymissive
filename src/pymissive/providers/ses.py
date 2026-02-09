from .base import MissiveProviderBase


class SESProvider(MissiveProviderBase):
    abstract = True
    name = "ses"
    display_name = "Amazon SES"
    description = "Amazon Simple Email Service - AWS transactional email"

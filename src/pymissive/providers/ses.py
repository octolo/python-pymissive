from .base import MissiveProviderBase


class SESProvider(MissiveProviderBase):
    name = "ses"
    display_name = "Amazon SES"
    description = "Amazon Simple Email Service - AWS transactional email"

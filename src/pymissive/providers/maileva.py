from .base import MissiveProviderBase


class MailevaProvider(MissiveProviderBase):
    abstract = True
    name = "Maileva"
    display_name = "Maileva"
    description = "Electronic postal mail and registered mail services"

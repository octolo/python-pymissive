from .base import MissiveProviderBase


class TelegramProvider(MissiveProviderBase):
    abstract = True
    name = "telegram"
    display_name = "Telegram"
    description = "Secure instant messaging with bots"

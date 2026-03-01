from .base import MissiveProviderBase


class SignalProvider(MissiveProviderBase):
    abstract = True
    name = "signal"
    display_name = "Signal"
    description = "Secure end-to-end encrypted messaging"

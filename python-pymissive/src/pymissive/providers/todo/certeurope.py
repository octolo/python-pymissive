from .base import MissiveProviderBase


class CerteuropeProvider(MissiveProviderBase):
    abstract = True
    name = "certeurope"
    display_name = "Certeurope (ERE)"
    description = "Registered email with legal value"

from .base import MissiveProviderBase


class CerteuropeProvider(MissiveProviderBase):
    abstract = True
    name = "certeurope"
    display_name = "Certeurope (LRE)"
    description = "Electronic registered email with legal value (LRE)"

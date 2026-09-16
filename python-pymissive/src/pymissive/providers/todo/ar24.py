from .base import MissiveProviderBase


class AR24Provider(MissiveProviderBase):
    abstract = True
    name = "ar24"
    display_name = "AR24 (ERE)"
    description = "Registered email with legal value"

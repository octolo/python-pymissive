from .base import MissiveProviderBase


class AR24Provider(MissiveProviderBase):
    abstract = True
    name = "ar24"
    display_name = "AR24 (LRE)"
    description = "Electronic registered email (LRE) with legal value"

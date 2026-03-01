from .base import MissiveProviderBase


class LaposteProvider(MissiveProviderBase):
    abstract = True
    name = "La Poste"
    display_name = "La Poste"
    description = "Registered mail and AR email sending on French territory"

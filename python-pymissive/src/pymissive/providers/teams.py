from .base import MissiveProviderBase


class TeamsProvider(MissiveProviderBase):
    abstract = True
    name = "teams"
    display_name = "Microsoft Teams"
    description = "Microsoft Teams - Enterprise communication (Microsoft 365)"

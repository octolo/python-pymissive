"""Manager for missive providers."""

from django_providerkit.managers import BaseProviderManager


class ProviderManager(BaseProviderManager):
    """Manager for missive providers."""

    package_name = "pymissive"

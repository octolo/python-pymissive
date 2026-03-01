"""Provider model for missive providers."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from virtualqueryset.models import VirtualModel
from django_providerkit.models.define import define_provider_fields, define_service_fields
from django_providerkit.managers import BaseProviderManager
from pymissive.providers.base import MissiveProviderBase


services = list(MissiveProviderBase.services_cfg.keys())


@define_provider_fields(primary_key="name")
@define_service_fields(services)
class MissiveProviderModel(VirtualModel):
    """Virtual model for missive providers."""

    name: models.CharField = models.CharField(
        max_length=255,
        verbose_name=_("Name"),
        help_text=_("Provider name (e.g., sendgrid)"),
        primary_key=True,
    )

    objects = BaseProviderManager(package_name='pymissive')

    class Meta:
        managed = False
        app_label = "django_pymissive"
        verbose_name = _("Provider")
        verbose_name_plural = _("Providers")
        ordering = ["-priority", "name"]

    def __str__(self) -> str:
        display = getattr(self, "display_name", None)
        return str(display or self.name)

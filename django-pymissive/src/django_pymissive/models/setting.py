"""In-memory setting rows. Nothing is stored in the database."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from virtualqueryset.models import VirtualModel

from ..managers.setting import MissiveSettingManager


class MissiveSetting(VirtualModel):
    """One Django setting read by this package."""

    name = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name=_("Setting"),
    )
    default_value = models.TextField(blank=True, verbose_name=_("Default"))
    configured_value = models.TextField(blank=True, verbose_name=_("Configured"))

    objects = MissiveSettingManager()

    class Meta:
        managed = False
        app_label = "django_pymissive"
        verbose_name = _("Setting")
        verbose_name_plural = _("Settings")
        ordering = ["name"]

    def __str__(self) -> str:
        return str(self.name)

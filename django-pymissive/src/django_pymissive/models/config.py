"""Config model for default provider per missive type."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .choices import MissiveType
from django_providerkit import ProviderField

class MissiveConfig(models.Model):
    """Default provider configuration per missive type.
    When a missive has no provider set, the default for its type is used.
    Allows live switching (e.g. Brevo down -> change to SendGrid).
    """

    missive_type = models.CharField(
        max_length=50,
        choices=MissiveType.choices,
        unique=True,
        verbose_name=_("Missive type"),
        help_text=_("Type of missive (email, sms, postal, etc.)"),
    )
    default_provider = ProviderField(
        package_name="pymissive",
        blank=True,
        verbose_name=_("Default provider"),
        help_text=_("Provider name (e.g. brevo, sendgrid). Leave empty for no default."),
    )

    class Meta:
        verbose_name = _("Configuration")
        verbose_name_plural = _("Configurations")
        ordering = ["missive_type"]

    def __str__(self):
        return f"{self.get_missive_type_display()} → {self.default_provider or '-'}"

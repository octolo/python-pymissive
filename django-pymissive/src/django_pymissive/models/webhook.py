"""Webhook model for storing webhook configurations."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from .choices import MissiveType

from pymissive.config import MISSIVE_WEBHOOK_FIELDS
from django_providerkit import fields_associations
from ..managers.webhook import MissiveWebhookManager

from django_providerkit import ProviderField


class MissiveWebhook(models.Model):
    """Webhook configuration for missive events."""

    provider = ProviderField(
        package_name="pymissive",
        blank=True,
        null=True,
        verbose_name=_("Provider"),
        help_text=_("Provider used to send this missive"),
    )
    webhook_id = models.CharField(
        max_length=255,
        verbose_name=_("Webhook ID"),
        help_text=_("Webhook ID"),
        primary_key=True,
    )

    objects = MissiveWebhookManager()

    class Meta:
        managed = False
        verbose_name = _("Webhook")
        verbose_name_plural = _("Webhooks")
        ordering = ["-created_at"]

    def __str__(self):
        return self.webhook_id

    def get_provider(self):
        if getattr(self.provider, "_provider", None):
            return self.provider
        from ..models.provider import MissiveProviderModel
        provider = self.provider_name
        return MissiveProviderModel.objects.get(name=provider)

    @property
    def provider_name(self):
        return self.webhook_id.split("-")[0]

    def get_webhook_data(self):
        return {"id": self.id, "type": self.type, "url": self.url}

    def new_webhook(self):
        service = f"set_webhook_{self.type}"
        provider = self.get_provider()
        if hasattr(provider._provider, service):
            return provider._provider.call_service(
                service, webhook_data=self.get_webhook_data()
            )

    def update_webhook(self):
        service = f"update_webhook_{self.type}"
        provider = self.get_provider()
        if hasattr(provider._provider, service):
            return provider._provider.call_service(
                service, webhook_data=self.get_webhook_data()
            )

    def save(self, *args, **kwargs):
        self.webhook_id = (
            self.new_webhook() if not self.webhook_id else self.update_webhook()
        )

    def delete(self):
        service = f"delete_webhook_{self.type}".lower()
        provider = self.get_provider()
        if hasattr(provider._provider, service):
            provider._provider.call_service(
                service, webhook_data=self.get_webhook_data()
            )


for field, cfg in MISSIVE_WEBHOOK_FIELDS.items():
    if field != "webhook_id":
        field_cfg = {
            "verbose_name": cfg["label"],
            "help_text": cfg["description"],
        }
        if field == "type":
            field_cfg["choices"] = MissiveType.choices
        db_field = fields_associations[cfg["format"]](**field_cfg)
        MissiveWebhook.add_to_class(field, db_field)

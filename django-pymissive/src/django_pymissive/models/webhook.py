"""Webhook model for storing webhook configurations."""

from django.db import models
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.utils.translation import gettext_lazy as _
from virtualqueryset.models import VirtualModel

from .choices import MissiveType, WebhookScheme

from pymissive.config import WEBHOOK_FIELDS
from ..utils import (
    get_default_domain,
    get_default_scheme,
    build_webhook_url,
    webhook_url_token_for,
)
from django_providerkit import fields_associations, ProviderField
from ..managers.webhook import MissiveWebhookManager


def get_default_webhook_scheme():
    """Return default scheme for webhook (serializable for migrations)."""
    return WebhookScheme.HTTPS if get_default_scheme() == "https" else WebhookScheme.HTTP


WEBHOOK_FIELD_MAX_LENGTHS = {
    "id": 255,
    "external_id": 255,
    "type": 50,
    "url": 2000,
    "event": 50,
    "reason": 500,
}


class MissiveWebhook(VirtualModel):
    """Webhook configuration stored on the provider, not in Django."""

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
    scheme = models.CharField(
        max_length=5,
        choices=WebhookScheme.choices,
        default=get_default_webhook_scheme,
        blank=True,
        verbose_name=_("Scheme"),
        help_text=_("HTTP or HTTPS"),
    )
    domain = models.CharField(
        max_length=255,
        blank=True,
        default=get_default_domain,
        verbose_name=_("Domain"),
        help_text=_(
            "Base domain (e.g. example.com). Webhook path is built from provider and type."
        ),
    )

    objects = MissiveWebhookManager()

    class Meta:
        managed = False
        app_label = "django_pymissive"
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
        if getattr(self, "webhook_id", None):
            return self.webhook_id.split("-")[0]
        provider = getattr(self, "provider", None)
        return getattr(provider, "name", None) or str(provider) if provider else ""

    def _get_url(self):
        """Return URL from provider data, or build from scheme+domain."""
        scheme = getattr(self, "scheme", None) or "https"
        domain = getattr(self, "domain", None)
        if domain:
            base = f"{scheme}://{(domain or '').strip().lstrip('/')}"
            token = ""
            try:
                token = webhook_url_token_for(self.get_provider())
            except Exception:
                token = ""
            return build_webhook_url(base, self.provider_name, self.type, token=token)
        return ""

    def get_webhook_data(self):
        url = getattr(self, "url", None) or self._get_url()
        return {"id": self.id, "webhook_id": self.webhook_id, "type": self.type, "url": url}

    def new_webhook(self):
        service = f"create_webhook_{self.type}"
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
        """Persist on the provider. ``VirtualModel.save`` raises — do not call it."""
        created = not self.webhook_id
        using = kwargs.get("using")
        update_fields = kwargs.get("update_fields")
        pre_save.send(
            sender=type(self),
            instance=self,
            raw=False,
            using=using,
            update_fields=update_fields,
        )
        webhook_id = self.new_webhook() if created else self.update_webhook()
        if webhook_id:
            self.webhook_id = webhook_id
        self._state.adding = False
        post_save.send(
            sender=type(self),
            instance=self,
            created=created,
            raw=False,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, using=None, keep_parents=False):
        """Remove on the provider. ``VirtualModel.delete`` raises — do not call it."""
        pre_delete.send(sender=type(self), instance=self, using=using)
        service = f"delete_webhook_{self.type}".lower()
        provider = self.get_provider()
        if hasattr(provider._provider, service):
            provider._provider.call_service(
                service, webhook_data=self.get_webhook_data()
            )
        post_delete.send(sender=type(self), instance=self, using=using)
        return 1, {self._meta.label: 1}


for field, cfg in WEBHOOK_FIELDS.items():
    if field not in ("webhook_id", "scheme", "domain"):
        field_cfg = {
            "verbose_name": cfg["label"],
            "help_text": cfg["description"],
        }
        if field == "type":
            field_cfg["choices"] = MissiveType.choices
        if cfg["format"] == "str":
            field_cfg["max_length"] = WEBHOOK_FIELD_MAX_LENGTHS.get(field, 255)
        db_field = fields_associations[cfg["format"]](**field_cfg)
        MissiveWebhook.add_to_class(field, db_field)

"""Webhook model for storing webhook configurations."""

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .choices import MissiveType, WebhookScheme

from pymissive.config import MISSIVE_WEBHOOK_FIELDS
from ..utils import get_default_domain, get_default_scheme
from django_providerkit import fields_associations


def get_default_webhook_scheme():
    """Return default scheme for webhook (serializable for migrations)."""
    return WebhookScheme.HTTPS if get_default_scheme() == "https" else WebhookScheme.HTTP
from ..managers.webhook import MissiveWebhookManager

from django_providerkit import ProviderField


def build_webhook_url(domain: str, provider_name: str, missive_type: str) -> str:
    """Build full webhook URL from domain, provider and missive type."""
    domain = (domain or "").rstrip("/")
    path = reverse(
        "django_pymissive:missive_webhook",
        kwargs={"provider": provider_name, "missive_type": missive_type},
    )
    return f"{domain}{path}"


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
            return build_webhook_url(base, self.provider_name, self.type)
        return ""

    def get_webhook_data(self):
        return {"id": self.id, "type": self.type, "url": self._get_url()}

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
    if field not in ("webhook_id", "scheme", "domain"):
        field_cfg = {
            "verbose_name": cfg["label"],
            "help_text": cfg["description"],
        }
        if field == "type":
            field_cfg["choices"] = MissiveType.choices
        db_field = fields_associations[cfg["format"]](**field_cfg)
        MissiveWebhook.add_to_class(field, db_field)

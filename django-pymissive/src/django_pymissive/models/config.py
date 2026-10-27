"""Config model for default provider per missive type."""

import logging

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_providerkit import ProviderField
from pymissive.config import normalize_missive_type

from .choices import MissiveType

logger = logging.getLogger(__name__)


def _provider_entry(entry, fallback, by_type):
    if isinstance(entry, str):
        return entry.strip() or fallback
    if not isinstance(entry, dict):
        logger.warning(
            "PYMISSIVE_DEFAULT_PROVIDER: ignored entry %r (expected a str or a dict)",
            entry,
        )
        return fallback
    for key, provider in entry.items():
        _set_typed_provider(by_type, key, provider)
    return fallback


def _set_typed_provider(by_type, key, provider):
    canonical = normalize_missive_type(str(key)) or ""
    name = str(provider or "").strip()
    if not canonical:
        logger.warning("PYMISSIVE_DEFAULT_PROVIDER: unknown missive type %r", key)
    elif not name:
        logger.warning("PYMISSIVE_DEFAULT_PROVIDER: empty provider for %r", key)
    else:
        by_type[canonical] = name


def _provider_setting() -> tuple[str, dict[str, str]]:
    """Return ``(fallback, per_type)`` from ``PYMISSIVE_DEFAULT_PROVIDER``.

    A string is only the fallback. Dict entries such as ``{"email": "brevo"}``
    are the per-type providers. A plain string never becomes a config row.
    Entries that cannot be used (another type, an unknown missive type, an
    empty provider) are skipped with a warning, so a typo does not go unseen.
    """
    raw = getattr(settings, "PYMISSIVE_DEFAULT_PROVIDER", None)
    if isinstance(raw, str):
        return raw.strip(), {}
    if not raw:
        return "", {}
    fallback = ""
    by_type: dict[str, str] = {}
    for entry in raw:
        fallback = _provider_entry(entry, fallback, by_type)
    return fallback, by_type


def typed_default_providers() -> dict[str, str]:
    """Per-type providers from the setting. Strings are ignored."""
    return dict(_provider_setting()[1])


def typed_default_provider_changes() -> tuple[list[tuple[str, str | None, str]], int]:
    """What loading the per-type providers would change.

    Returns ``(changes, unchanged)``. Each change is ``(missive_type,
    current, provider)`` where ``current`` is ``None`` for a type without a
    config row, or the provider about to be replaced.
    """
    wanted = typed_default_providers()
    current = {
        missive_type: str(provider or "")
        for missive_type, provider in MissiveConfig.objects.filter(missive_type__in=wanted).values_list(
            "missive_type", "default_provider"
        )
    }
    changes = [
        (missive_type, current.get(missive_type), provider)
        for missive_type, provider in wanted.items()
        if current.get(missive_type) != provider
    ]
    return changes, len(wanted) - len(changes)


def load_typed_default_providers() -> tuple[int, int, int]:
    """Write the per-type providers that differ. Returns created, replaced, unchanged."""
    changes, unchanged = typed_default_provider_changes()
    created = replaced = 0
    for missive_type, current, provider in changes:
        MissiveConfig.objects.update_or_create(
            missive_type=missive_type,
            defaults={"default_provider": provider},
        )
        if current is None:
            created += 1
        else:
            replaced += 1
    return created, replaced, unchanged


def default_provider_for_type(missive_type: str) -> str:
    """Provider from ``PYMISSIVE_DEFAULT_PROVIDER`` for one missive type.

    A string is the provider for every type. A list may mix that default
    with per-type overrides, for example
    ``["fake", {"email": "brevo"}, {"sms": "smspartner"}]``.
    The last non-empty string in the list is the fallback. A type named in
    a dict wins over it.
    """
    fallback, by_type = _provider_setting()
    channel = normalize_missive_type(missive_type) or ""
    return by_type.get(channel) or fallback


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
        help_text=_("Type of missive (email, sms, letter, registered_letter, etc.)"),
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

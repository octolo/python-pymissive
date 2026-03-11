"""Missive model choices."""

from typing import Optional

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from pymissive.config import (
    MISSIVE_ACKNOWLEDGEMENT_LEVELS,
    MISSIVE_TYPES,
    MISSIVE_EVENT_SUCCESS,
    MISSIVE_EVENT_INFO,
    MISSIVE_EVENT_FAILED,
    MISSIVE_GENERIC_SUPPORT,
    MISSIVE_DELIVERY_MODES,
    MISSIVE_PRIORITIES,
)


def is_enable_setting(setting):
    return getattr(settings, f"MISSIVE_{setting}".upper(), True)


# Python UPPERCASE, DB lowercase (config key), label capitalize
MissiveSupport = models.TextChoices(
    "MissiveSupport",
    {k.upper(): (k, _(k.capitalize())) for k in MISSIVE_GENERIC_SUPPORT},
)


def get_missive_support_from_type(missive_type: str) -> str:
    """Get the missive support from the type. Returns DB value (lowercase)."""
    if not missive_type:
        return ""
    mt = str(missive_type).lower()
    for key, values in MISSIVE_GENERIC_SUPPORT.items():
        if mt in [str(v).lower() for v in values]:
            return key
    return ""


_MISSIVE_EVENT_STYLE_MAP = {
    **{k: "success" for k in MISSIVE_EVENT_SUCCESS.keys()},
    **{k: "info" for k in MISSIVE_EVENT_INFO.keys()},
    **{k: "danger" for k in MISSIVE_EVENT_FAILED.keys()},
}


class MissiveStatus(models.TextChoices):
    """High-level missive workflow status."""

    DRAFT = "draft", _("Draft")
    PROCESSING = "processing", _("Processing")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    ERROR = "error", _("Error")
    CANCELLED = "cancelled", _("Cancelled")


# Python UPPERCASE, DB lowercase, label from config (already localized in translation_catalog)
def _event_key(k):
    return k.upper().replace("-", "_").replace(" ", "_")

MissiveEventType = models.TextChoices(
    "MissiveEventType",
    {
        **{_event_key(k): (k.lower(), _(v)) for k, v in MISSIVE_EVENT_SUCCESS.items()},
        **{_event_key(k): (k.lower(), _(v)) for k, v in MISSIVE_EVENT_INFO.items()},
        **{_event_key(k): (k.lower(), _(v)) for k, v in MISSIVE_EVENT_FAILED.items()},
    },
)

# Python UPPERCASE, DB lowercase (from config), label capitalize
MissiveDeliveryMode = models.TextChoices(
    "MissiveDeliveryMode",
    {
        **{k.upper(): (k, _(k.capitalize())) for k in MISSIVE_DELIVERY_MODES if is_enable_setting(k)},
    },
)

MissivePriority = models.TextChoices(
    "MissivePriority",
    {
        **{k.upper(): (k, _(k.capitalize())) for k in MISSIVE_PRIORITIES if is_enable_setting(k)},
    },
)


# Styles by DB value (lowercase) or legacy uppercase
MISSIVE_STYLE_MAP = {
    **_MISSIVE_EVENT_STYLE_MAP,
    "draft": "secondary",
    "processing": "info",
    "success": "success",
    "failed": "warning",
    "error": "danger",
    "low": "info",
    "normal": "secondary",
    "high": "warning",
    "urgent": "danger",
    "economic": "secondary",
    "premium": "info",
    "express": "warning",
    "history": "secondary",
    "message": "primary",
    "missive": "info",
}


def get_missive_style(name: str) -> str:
    """Return the style associated with a name. Accepts DB value (lowercase) or legacy uppercase."""
    return MISSIVE_STYLE_MAP.get(name) or MISSIVE_STYLE_MAP.get((name or "").lower(), "info")


def event_to_status(event: Optional[str]) -> str:
    """Map MissiveEventType to MissiveStatus."""
    if not event:
        return MissiveStatus.DRAFT
    if event in MISSIVE_EVENT_SUCCESS:
        return MissiveStatus.SUCCESS
    if event in MISSIVE_EVENT_FAILED:
        return MissiveStatus.FAILED
    if event == "draft":
        return MissiveStatus.DRAFT
    return MissiveStatus.PROCESSING


# Python UPPERCASE, DB lowercase (from config key), label from config
MissiveType = models.TextChoices(
    "MissiveType",
    {
        **{k.upper().replace("-", "_"): (k, _(v)) for k, v in MISSIVE_TYPES.items()},
    },
)


class WebhookScheme(models.TextChoices):
    """HTTP scheme for webhook URL."""

    HTTPS = "https", _("HTTPS")
    HTTP = "http", _("HTTP")


AcknowledgementLevel = models.TextChoices(
    "AcknowledgementLevel", 
    {
        **{level["name"].upper(): (level["name"], _(level["display_name"])) 
        for level in MISSIVE_ACKNOWLEDGEMENT_LEVELS if is_enable_setting(level["name"])},
    }
)



class MissiveRecipientType(models.TextChoices):
    """Recipient types."""

    RECIPIENT = "recipient", _("Recipient")
    CC = "cc", _("CC")
    BCC = "bcc", _("BCC")


class MessageDirection(models.TextChoices):
    """Message direction in an exchange."""

    INBOUND = "inbound", _("Inbound")
    OUTBOUND = "outbound", _("Outbound")


class MissiveAttachmentType(models.TextChoices):
    """Attachment types."""

    VIRTUAL_ATTACHMENT = "virtual_attachment", _("Virtual Attachment")
    ATTACHMENT = "attachment", _("Attachment")
    SIGNATURE = "signature", _("Signature")
    RECEIPT = "receipt", _("Receipt")
    PROOF = "proof", _("Proof")
    OTHER = "other", _("Other")


class MissiveThreadType(models.TextChoices):
    """Thread types."""

    MISSIVE = "missive", _("Missive")
    MESSAGE = "message", _("Message")
    HISTORY = "history", _("History")
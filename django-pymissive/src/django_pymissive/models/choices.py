"""Missive model choices."""

from typing import Optional

from django.db import models
from django.utils.translation import gettext_lazy as _

from pymissive.config import (
    MISSIVE_ACKNOWLEDGEMENT_LEVELS,
    MISSIVE_TYPES,
    MISSIVE_EVENT_SUCCESS,
    MISSIVE_EVENT_INFO,
    MISSIVE_EVENT_FAILED,
    MISSIVE_GENERIC_SUPPORT,
)


MissiveSupport = models.TextChoices(
    "MissiveSupport",
    {k: (k, _(k.capitalize())) for k in MISSIVE_GENERIC_SUPPORT.keys()},
)


def get_missive_support_from_type(missive_type: str) -> str:
    """Get the missive support from the type."""
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


MissiveEventType = models.TextChoices(
    "MissiveEventType",
    {
        **{k.upper(): (f"{k}", _(v)) for k, v in MISSIVE_EVENT_SUCCESS.items()},
        **{k.upper(): (f"{k}", _(v)) for k, v in MISSIVE_EVENT_INFO.items()},
        **{k.upper(): (f"{k}", _(v)) for k, v in MISSIVE_EVENT_FAILED.items()},
    },
)


class MissivePriority(models.TextChoices):
    """Priority levels."""

    LOW = "LOW", _("Low")
    NORMAL = "NORMAL", _("Normal")
    HIGH = "HIGH", _("High")
    URGENT = "URGENT", _("Urgent")


MISSIVE_STYLE_MAP = {
    **_MISSIVE_EVENT_STYLE_MAP,
    "draft": "secondary",
    "processing": "info",
    "success": "success",
    "failed": "warning",
    "error": "danger",
    "LOW": "info",
    "NORMAL": "secondary",
    "HIGH": "warning",
    "URGENT": "danger",
}


def get_missive_style(name: str) -> str:
    """Return the style associated with a name."""
    return MISSIVE_STYLE_MAP.get(name, "info")


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


choices_missive_modes = {
    type_key: (type_key, _(type_description))
    for type_key, type_description in MISSIVE_TYPES.items()
}

MissiveType = models.TextChoices("MissiveMode", choices_missive_modes)

choices_acknowledgement_levels = {
    level["name"].upper(): (level["name"], _(level["display_name"]))
    for level in MISSIVE_ACKNOWLEDGEMENT_LEVELS
}

AcknowledgementLevel = models.TextChoices(
    "AcknowledgementLevel", choices_acknowledgement_levels
)


class MissiveRecipientType(models.TextChoices):
    """Recipient types."""

    RECIPIENT = "recipient", _("Recipient")
    REPLY_TO = "reply_to", _("Reply To")
    CC = "cc", _("CC")
    BCC = "bcc", _("BCC")


class MissiveAttachmentType(models.TextChoices):
    """Attachment types."""

    VIRTUAL_ATTACHMENT = "virtual_attachment", _("Virtual Attachment")
    ATTACHMENT = "attachment", _("Attachment")
    SIGNATURE = "signature", _("Signature")
    RECEIPT = "receipt", _("Receipt")
    PROOF = "proof", _("Proof")
    OTHER = "other", _("Other")

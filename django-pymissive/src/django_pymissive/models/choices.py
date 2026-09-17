"""Missive model choices."""

from typing import Optional

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from pymissive.config import (
    MISSIVE_ACKNOWLEDGEMENT_LEVELS,
    MISSIVE_TYPES,
    SUCCESSFUL_EVENTS,
    INFO_EVENTS,
    FAILED_EVENTS,
    GENERIC_SUPPORT,
    DELIVERY_MODES,
    PRIORITIES,
    missive_support_for_type,
    missive_types_for_support,
)


def is_enable_setting(setting):
    return getattr(settings, f"MISSIVE_{setting}".upper(), True)


# Python UPPERCASE, DB lowercase (config key), label capitalize
MissiveSupport = models.TextChoices(
    "MissiveSupport",
    {k.upper(): (k, _(k.capitalize())) for k in GENERIC_SUPPORT},
)


def get_missive_support_from_type(missive_type: str) -> str:
    """Get the missive support from the type. Returns DB value (lowercase)."""
    return missive_support_for_type(missive_type)


def missive_type_filter(support: str, prefix: str = "") -> dict:
    """ORM filter kwargs selecting every missive type of ``support``.

    ``prefix`` is the lookup path leading to the missive: ``""`` on a ``Missive``
    queryset, ``"missive"`` from a ``MissiveRelatedObject``, ``"to_missive"``
    from a campaign or a scheduled run.

    Raises:
        ValueError: for an unknown support — returning an empty filter would
            silently widen the queryset to every missive instead.
    """
    types = missive_types_for_support(support)
    if not types:
        raise ValueError(f"Unknown missive support: {support!r}")
    field = f"{prefix}__missive_type" if prefix else "missive_type"
    return {f"{field}__in": types}


_MISSIVE_EVENT_STYLE_MAP = {
    **{k: "success" for k in SUCCESSFUL_EVENTS.keys()},
    **{k: "info" for k in INFO_EVENTS.keys()},
    **{k: "danger" for k in FAILED_EVENTS.keys()},
}


class MissiveStatus(models.TextChoices):
    """High-level missive workflow status."""

    DRAFT = "draft", _("Draft")
    PROCESSING = "processing", _("Processing")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    PARTIALLY_SUCCESS = "partially_success", _("Partially success")
    PARTIALLY_FAILED = "partially_failed", _("Partially failed")
    ERROR = "error", _("Error")
    CANCELLED = "cancelled", _("Cancelled")


#: Statuses of a missive still waiting to be sent. The empty string is a legacy
#: value found in databases predating the ``draft`` default.
PENDING_STATUSES = (MissiveStatus.DRAFT, "")

#: Statuses of a send that did not go through.
ERROR_STATUSES = (
    MissiveStatus.FAILED,
    MissiveStatus.PARTIALLY_FAILED,
    MissiveStatus.ERROR,
)

#: Statuses ``set_status()`` must not leave. A cancel is a user/provider
#: decision; recounting last delivery events would silently restore
#: DRAFT/PROCESSING/SUCCESS and put the send button back.
TERMINAL_STATUSES = (MissiveStatus.CANCELLED,)

#: Last-event value that means the send was cancelled (see FAILED_EVENTS).
CANCELLED_EVENT = "cancelled"


def _status_field(prefix: str) -> str:
    return f"{prefix}__status" if prefix else "status"


def sent_missive_q(prefix: str = "") -> Q:
    """``Q`` matching missives that left the pending state.

    ``prefix`` is the lookup path leading to the missive (see
    :func:`missive_type_filter`).

    ``status__isnull=False`` is stated rather than left to the negation: on the
    ``LEFT JOIN`` of a campaign or a run without missives, ``~Q(status__in=…)``
    also matches the NULL row the join produces.
    """
    field = _status_field(prefix)
    return Q(**{f"{field}__isnull": False}) & ~Q(**{f"{field}__in": PENDING_STATUSES})


def pending_missive_q(prefix: str = "") -> Q:
    """``Q`` matching missives still waiting to be sent (draft or legacy empty)."""
    return Q(**{f"{_status_field(prefix)}__in": PENDING_STATUSES})


def error_missive_q(prefix: str = "") -> Q:
    """``Q`` matching missives whose send failed."""
    return Q(**{f"{_status_field(prefix)}__in": ERROR_STATUSES})


# Python UPPERCASE, DB lowercase, label from config (already localized in translation_catalog)
def _event_key(k):
    return k.upper().replace("-", "_").replace(" ", "_")

def _event_label(v):
    """Extract translatable label from config value (str or (label, description) tuple)."""
    return v[0] if isinstance(v, tuple) else v


def _event_reason(v):
    """Extract reason from config value (second element of tuple, or empty string)."""
    return v[1] if isinstance(v, tuple) and len(v) > 1 else ""


# Map event value (DB) -> translatable reason for get_description()
_EVENT_REASONS = {
    **{k: _(v[1]) if isinstance(v, tuple) and len(v) > 1 else "" for k, v in SUCCESSFUL_EVENTS.items()},
    **{k: _(v[1]) if isinstance(v, tuple) and len(v) > 1 else "" for k, v in INFO_EVENTS.items()},
    **{k: _(v[1]) if isinstance(v, tuple) and len(v) > 1 else "" for k, v in FAILED_EVENTS.items()},
}

MissiveEventType = models.TextChoices(
    "MissiveEventType",
    {
        **{_event_key(k): (k.lower(), _(_event_label(v))) for k, v in SUCCESSFUL_EVENTS.items()},
        **{_event_key(k): (k.lower(), _(_event_label(v))) for k, v in INFO_EVENTS.items()},
        **{_event_key(k): (k.lower(), _(_event_label(v))) for k, v in FAILED_EVENTS.items()},
    },
)


def _get_event_reason(event_value: Optional[str]) -> str:
    """Return config reason for event, or empty string if unknown."""
    return _EVENT_REASONS.get(event_value or "", "")


MissiveEventType.get_description = classmethod(
    lambda cls, event_value: _get_event_reason(event_value)
)

# Python UPPERCASE, DB lowercase (from config), label capitalize
MissiveDeliveryMode = models.TextChoices(
    "MissiveDeliveryMode",
    {
        **{k.upper(): (k, _(k.capitalize())) for k in DELIVERY_MODES if is_enable_setting(k)},
    },
)

MissivePriority = models.TextChoices(
    "MissivePriority",
    {
        **{k.upper(): (k, _(k.capitalize())) for k in PRIORITIES if is_enable_setting(k)},
    },
)


# Styles by DB value (lowercase) or legacy uppercase
MISSIVE_STYLE_MAP = {
    **_MISSIVE_EVENT_STYLE_MAP,
    "draft": "secondary",
    "processing": "info",
    "success": "success",
    "failed": "warning",
    "partially_success": "info",
    "partially_failed": "warning",
    "error": "danger",
    "cancelled": "secondary",
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
    "recipient": "info",
    "cc": "secondary",
    "bcc": "secondary",
    "notification": "primary",
}


def get_missive_style(name: str) -> str:
    """Return the style associated with a name. Accepts DB value (lowercase) or legacy uppercase."""
    return MISSIVE_STYLE_MAP.get(name) or MISSIVE_STYLE_MAP.get((name or "").lower(), "info")


def event_to_status(event: Optional[str]) -> str:
    """Map MissiveEventType to MissiveStatus."""
    if not event:
        return MissiveStatus.DRAFT
    if event in SUCCESSFUL_EVENTS:
        return MissiveStatus.SUCCESS
    if event in FAILED_EVENTS:
        return MissiveStatus.FAILED
    if event == "draft":
        return MissiveStatus.DRAFT
    return MissiveStatus.PROCESSING


def status_from_event_counts(
    success_count: int,
    processing_count: int,
    failed_count: int,
    cancelled_count: int = 0,
) -> str:
    """Derive MissiveStatus from counts of last events per recipient/missive."""
    total = success_count + processing_count + failed_count + cancelled_count
    if total == 0:
        return MissiveStatus.DRAFT
    if cancelled_count == total:
        return MissiveStatus.CANCELLED
    failed_count += cancelled_count
    if failed_count == total:
        return MissiveStatus.FAILED
    if failed_count > 0 and success_count > 0:
        return MissiveStatus.PARTIALLY_FAILED
    if failed_count > 0:
        return MissiveStatus.FAILED
    if success_count == total:
        return MissiveStatus.SUCCESS
    if success_count > 0 and processing_count > 0:
        return MissiveStatus.PARTIALLY_SUCCESS
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
    NOTIFICATION = "notification", _("Notification")


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
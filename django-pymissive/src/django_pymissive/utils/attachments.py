"""Attachment ordering and validation helpers."""

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def recalculate_attachment_priorities(missive_id=None, campaign_id=None):
    """
    Reassign priorities: first-document stays at 0, others get 1, 2, 3...
    Use after inline save or when priority changed programmatically.
    """
    if not missive_id and not campaign_id:
        return
    from django.db import transaction

    from ..models.attachment import (
        FIRST_DOCUMENT_PRIORITY,
        MissiveBaseAttachment,
        _page_order_q,
    )

    with transaction.atomic():
        if missive_id:
            from ..models.missive import Missive

            list(Missive.objects.select_for_update().filter(pk=missive_id))
            qs = MissiveBaseAttachment.objects.filter(missive_id=missive_id)
        else:
            from ..models.campaign import MissiveCampaign

            list(MissiveCampaign.objects.select_for_update().filter(pk=campaign_id))
            qs = MissiveBaseAttachment.objects.filter(campaign_id=campaign_id)
        siblings = list(qs.filter(_page_order_q()).order_by("priority", "id"))
        to_update = []
        next_priority = FIRST_DOCUMENT_PRIORITY
        for att in siblings:
            if att.is_first_document:
                expected = FIRST_DOCUMENT_PRIORITY
            else:
                next_priority = max(next_priority + 1, 1)
                expected = next_priority
            if att.priority != expected:
                att.priority = expected
                to_update.append(att)
        if to_update:
            MissiveBaseAttachment.objects.bulk_update(to_update, ["priority"])


def _normalize_extension(ext: str) -> str:
    """Lowercase ``ext`` and ensure it starts with a dot. Empty string for falsy input."""
    if not ext:
        return ""
    e = str(ext).strip().lower()
    if not e:
        return ""
    return e if e.startswith(".") else f".{e}"


def _normalize_extensions(exts) -> list[str]:
    """Lowercase + leading-dot normalisation for a list of extensions."""
    if exts is None:
        return []
    return [_normalize_extension(e) for e in exts if _normalize_extension(e)]


def get_allowed_attachment_extensions(missive_type: str | None) -> list[str] | None:
    """Allowed attachment file extensions for ``missive_type``.

    Reads ``settings.PYMISSIVE_ALLOWED_ATTACHMENT_EXTENSIONS`` which can be:

    - **None / unset** → no restriction (any extension allowed).
    - **list/tuple** → applies the same list to every missive type.
    - **dict** → per-type override; supported keys are concrete missive types
      (``"email"``, ``"registered_letter"``, ``"letter"``, ``"sms"`` …) and the special ``"default"``
      entry used as a fallback when the missive type is not explicitly
      listed. A dict without a matching key and without ``"default"``
      means no restriction for that type.

    Each extension may be given with or without leading dot, in any case
    (``"pdf"``, ``".PDF"``, ``".pdf"`` are equivalent).

    Returns:
        - ``list[str]``: normalised allowed extensions (``[".pdf"]`` …).
        - ``[]``: attachments forbidden for this type.
        - ``None``: no restriction.
    """
    config = getattr(settings, "PYMISSIVE_ALLOWED_ATTACHMENT_EXTENSIONS", None)
    if config is None:
        return None
    if isinstance(config, (list, tuple, set, frozenset)):
        return _normalize_extensions(config)
    if isinstance(config, dict):
        from pymissive.config import normalize_missive_type

        mt = (missive_type or "").lower()
        if mt in config:
            return _normalize_extensions(config[mt])
        canonical = normalize_missive_type(mt)
        if canonical and canonical in config:
            return _normalize_extensions(config[canonical])
        if "default" in config:
            return _normalize_extensions(config["default"])
        return None
    return None


def is_attachment_allowed(filename: str, missive_type: str | None) -> bool:
    """Return True if the given filename's extension is allowed for ``missive_type``."""
    allowed = get_allowed_attachment_extensions(missive_type)
    if allowed is None:
        return True
    if not allowed:
        return False
    if not filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in allowed


def validate_attachment_for_missive_type(filename: str, missive_type: str | None) -> None:
    """Raise :class:`~django.core.exceptions.ValidationError` if the file is not allowed.

    No-op when no restriction is configured. Suitable for use inside
    ``Model.clean`` or wherever attachment validation is needed.
    """
    allowed = get_allowed_attachment_extensions(missive_type)
    if allowed is None:
        return
    if not allowed:
        raise ValidationError(
            _("Attachments are not allowed for missive type '%(type)s'.") % {"type": missive_type or "?"}
        )
    if not filename:
        raise ValidationError(_("Attachment filename is required to validate against allowed extensions."))
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        raise ValidationError(
            _("File extension '%(ext)s' is not allowed for missive type '%(type)s'. Allowed extensions: %(allowed)s.")
            % {
                "ext": ext or "(none)",
                "type": missive_type or "?",
                "allowed": ", ".join(allowed),
            }
        )

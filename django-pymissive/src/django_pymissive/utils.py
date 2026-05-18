"""Utility functions for django_pymissive."""

import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models.recipient import MissiveRecipient


def serialize_model_for_context(obj) -> dict:
    """Serialize a Django model instance to a plain dict safe for template context.

    Using a live model instance in a template context is a security risk because
    Django templates call attribute access — including zero-argument methods like
    ``delete()`` or ``save()``.  This function returns a plain ``dict`` with only
    serializable field values so no model methods are reachable from templates.

    - All concrete DB columns are included (including non-editable fields such as
      ``id`` / ``created_at``).
    - ForeignKey fields are serialised as ``<field_name>_id`` (raw integer/uuid),
      **not** as a nested model instance, to avoid re-introducing the same risk.
    - Many-to-many and reverse relations are intentionally excluded.
    """
    data = {
        field.attname: field.value_from_object(obj)
        for field in obj._meta.concrete_fields
    }
    if callable(getattr(obj, "to_context_dict", None)):
        data.update(obj.to_context_dict())
    return data


def recalculate_attachment_priorities(missive_id=None, campaign_id=None):
    """
    Reassign priorities: first-document stays at 0, others get 1, 2, 3...
    Use after inline save or when priority changed programmatically.
    """
    if not missive_id and not campaign_id:
        return
    from .models.attachment import FIRST_DOCUMENT_PRIORITY, MissiveBaseAttachment

    qs = MissiveBaseAttachment.objects
    if missive_id:
        qs = qs.filter(missive_id=missive_id)
    else:
        qs = qs.filter(campaign_id=campaign_id)
    siblings = list(qs.order_by("priority", "id"))
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


def get_default_domain():
    """Return default domain (host) from settings or localhost:8000.
    If setting is a full URL, extracts the netloc for use in webhook domain field.
    """
    domain = (
        getattr(settings, "MISSIVE_DOMAIN", None)
        or getattr(settings, "DOMAIN", None)
        or "localhost:8000"
    )
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        return parsed.netloc or domain
    return domain


def get_default_scheme():
    """Return default scheme from settings (MISSIVE_SCHEME, SCHEME) or http.
    If domain setting is a full URL, extracts scheme from it.
    """
    scheme = getattr(settings, "MISSIVE_SCHEME", None) or getattr(settings, "SCHEME", None)
    if scheme:
        return str(scheme).replace("://", "")
    domain = getattr(settings, "MISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None)
    if domain and str(domain).strip().lower().startswith("https://"):
        return "https"
    return "http"


def get_base_url(domain=None, scheme=None, trailing_slash=True):
    """
    Build base URL from domain and scheme.
    Defaults: domain=localhost:8000, scheme=http.
    Returns e.g. http://localhost:8000/ (with trailing_slash) or http://localhost:8000.
    """
    domain = domain or get_default_domain()
    scheme = scheme or get_default_scheme()
    scheme = str(scheme).replace("://", "")
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        base = domain.rstrip("/")
    else:
        base = f"{scheme}://{domain}"
    return f"{base}/" if trailing_slash else base


def build_webhook_url(domain: str, provider_name: str, missive_type: str) -> str:
    """Build full webhook URL from domain, provider and missive type."""
    domain = (domain or "").rstrip("/")
    path = reverse(
        "django_pymissive:missive_webhook",
        kwargs={"provider": provider_name, "missive_type": missive_type},
    )
    return f"{domain}{path}"


def get_recipient(missive, recipient_data):
    """Resolve recipient from missive and recipient_data dict."""
    if not isinstance(recipient_data, dict):
        return None
    try:
        return MissiveRecipient.objects.get(missive=missive, **recipient_data)
    except MissiveRecipient.DoesNotExist:
        return None


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
      (``"email"``, ``"lre"``, ``"sms"`` …) and the special ``"default"``
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
        mt = (missive_type or "").lower()
        if mt in config:
            return _normalize_extensions(config[mt])
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
            _("Attachments are not allowed for missive type '%(type)s'.")
            % {"type": missive_type or "?"}
        )
    if not filename:
        raise ValidationError(
            _("Attachment filename is required to validate against allowed extensions.")
        )
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        raise ValidationError(
            _(
                "File extension '%(ext)s' is not allowed for missive type "
                "'%(type)s'. Allowed extensions: %(allowed)s."
            )
            % {
                "ext": ext or "(none)",
                "type": missive_type or "?",
                "allowed": ", ".join(allowed),
            }
        )


def is_dry_run() -> bool:
    """Return True when provider calls must be skipped (test/staging dry-run mode).

    Controlled by ``settings.PYMISSIVE_DRY_RUN`` (preferred), or the alias
    ``settings.PYMISSIVE_DISABLE_SEND``. Defaults to False (real sends).

    When enabled, ``Missive.send_missive`` and ``Missive.prepare_missive``:

    - run the full local pipeline (campaign inheritance, body processors,
      first_document PDF generation, ``get_serialized_data``);
    - skip the provider call entirely;
    - persist a synthetic ``external_id`` prefixed with ``dry-run:``;
    - record a ``REQUEST`` event with ``trace={"dry_run": True, ...}`` so
      tests can assert the missive went through the pipeline.
    """
    if getattr(settings, "PYMISSIVE_DRY_RUN", False):
        return True
    return bool(getattr(settings, "PYMISSIVE_DISABLE_SEND", False))
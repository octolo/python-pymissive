"""Utility functions for django_pymissive."""

import os
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import FieldError, ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from .models.choices import MissiveRecipientType
from .models.recipient import MissiveRecipient


def serialize_model_for_context(obj) -> dict:
    """Plain dict for templates (no live model — avoids callable access like ``delete()``)."""
    data = {field.attname: field.value_from_object(obj) for field in obj._meta.concrete_fields}
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
    from django.db import transaction

    from .models.attachment import (
        FIRST_DOCUMENT_PRIORITY,
        MissiveBaseAttachment,
        _page_order_q,
    )

    with transaction.atomic():
        if missive_id:
            from .models.missive import Missive

            list(Missive.objects.select_for_update().filter(pk=missive_id))
            qs = MissiveBaseAttachment.objects.filter(missive_id=missive_id)
        else:
            from .models.campaign import MissiveCampaign

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


def get_default_domain():
    """Return default domain (host) from settings or localhost:8000.
    If setting is a full URL, extracts the netloc for use in webhook domain field.
    """
    domain = getattr(settings, "MISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None) or "localhost:8000"
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


def build_webhook_url(domain: str, provider_name: str, missive_type: str, token: str | None = None) -> str:
    """Build full webhook URL from domain, provider and missive type.

    ``token`` is the path secret for providers that cannot send an
    Authorization header (Scaleway SNS).
    """
    domain = (domain or "").rstrip("/")
    kwargs = {"provider": provider_name, "missive_type": missive_type}
    name = "django_pymissive:missive_webhook"
    if token:
        kwargs["token"] = token
        name = "django_pymissive:missive_webhook_token"
    path = reverse(name, kwargs=kwargs)
    return f"{domain}{path}"


def webhook_url_token_for(provider) -> str:
    """Path token when the provider requires one and a secret is set."""
    inner = getattr(provider, "_provider", provider)
    uses_token = getattr(inner, "webhook_uses_url_token", None)
    if not callable(uses_token) or not uses_token():
        return ""
    getter = getattr(inner, "get_webhook_secret", None)
    if not callable(getter):
        return ""
    return getter() or ""


def _recipient_lookup(qs, **kwargs):
    """Return a single recipient or None. Never raise on bad pk types."""
    try:
        return qs.get(**kwargs)
    except (
        MissiveRecipient.DoesNotExist,
        MissiveRecipient.MultipleObjectsReturned,
        ValueError,
        TypeError,
        ValidationError,
        FieldError,
    ):
        return None


def _first_recipient_match(qs, lookups):
    for field, value in lookups:
        if value in (None, ""):
            continue
        found = _recipient_lookup(qs, **{field: value})
        if found:
            return found
    return None


def get_recipient(missive, recipient_data):
    """Resolve recipient from missive and recipient_data dict.

    Do not pass the whole dict to ``.get(**data)``: Maileva retrieve events
    carry ``custom_id`` (often a UUID from another system) as ``id``, while
    the local pk may be an integer. Combining keys, or querying an integer
    pk with a UUID, raises ``ValueError`` and used to abort event handling.
    Match ``substitute_id`` first so imported history still resolves.
    """
    if not isinstance(recipient_data, dict):
        return None
    qs = MissiveRecipient.objects.filter(missive=missive)
    internal_id = recipient_data.get("id") or recipient_data.get("internal_id")
    substitute_id = recipient_data.get("substitute_id") or internal_id
    name = (recipient_data.get("name") or "").strip()
    external_id = recipient_data.get("external_id")
    email = recipient_data.get("email")
    phone = recipient_data.get("phone")
    found = _first_recipient_match(
        qs,
        (
            ("substitute_id", str(substitute_id) if substitute_id not in (None, "") else None),
            ("pk", internal_id),
            ("name", name),
            ("external_id", external_id),
            ("email", email),
            ("phone", phone),
        ),
    )
    if found:
        return found
    if internal_id or external_id or name:
        return _recipient_lookup(qs, recipient_type=MissiveRecipientType.RECIPIENT)
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


_PACKAGE_PREFIXES = ("django_pymissive.", "pymissive.")


def is_import_allowed(path: str) -> bool:
    """Whether a dotted path may be imported and called.

    ``settings.PYMISSIVE_ALLOWED_TASK_BACKENDS`` lists the allowed prefixes;
    unset (``None``) allows every path. The package's own modules are always
    allowed.
    """
    if path.startswith(_PACKAGE_PREFIXES):
        return True
    allowed = getattr(settings, "PYMISSIVE_ALLOWED_TASK_BACKENDS", None)
    if allowed is None:
        return True
    return any(path == entry or path.startswith(f"{entry}.") for entry in allowed)


def import_allowed_string(path: str):
    """``import_string`` restricted to :func:`is_import_allowed` paths."""
    if not is_import_allowed(path):
        raise ImportError(f"{path} is not allowed by settings.PYMISSIVE_ALLOWED_TASK_BACKENDS.")
    return import_string(path)


def processor_path(entry):
    """Dotted path of a processor entry, or ``None`` when it has none."""
    if isinstance(entry, dict):
        entry = entry.get("processor") or entry.get("path")
    elif isinstance(entry, (list, tuple)) and len(entry) == 2:
        entry = entry[0]
    return entry if isinstance(entry, str) else None


def validate_import_paths(instance, *field_names) -> None:
    """Raise ``ValidationError`` for paths in *field_names* that are not allowed.

    Each field holds a dotted path or a list of processor entries.
    """
    errors = {}
    for name in field_names:
        value = getattr(instance, name, None) or []
        entries = value if isinstance(value, list) else [value]
        refused = [path for path in map(processor_path, entries) if path and not is_import_allowed(path)]
        if refused:
            errors[name] = _("%(paths)s not allowed by settings.PYMISSIVE_ALLOWED_TASK_BACKENDS.") % {
                "paths": ", ".join(refused)
            }
    if errors:
        raise ValidationError(errors)


def _resolve_hook(hook):
    """Resolve a single hook (dotted path string or callable) to a callable."""
    return hook if callable(hook) else import_allowed_string(hook)


#: Target number of progress-hook calls over a full run.
PROGRESS_STEP_DEFAULT = 20


def progress_step_default() -> int:
    """Return ``settings.PYMISSIVE_PROGRESS_STEP`` (default 20).

    This is how many times a full run should call its progress hook. A value
    below 1 falls back to the default.
    """
    raw = getattr(settings, "PYMISSIVE_PROGRESS_STEP", PROGRESS_STEP_DEFAULT)
    try:
        step = int(raw)
    except (TypeError, ValueError):
        return PROGRESS_STEP_DEFAULT
    if step < 1:
        return PROGRESS_STEP_DEFAULT
    return step


#: Missives loaded at a time by a campaign send loop.
SEND_CHUNK_SIZE_DEFAULT = 500


def send_chunk_size() -> int:
    """Return ``settings.PYMISSIVE_SEND_CHUNK_SIZE`` (default 500).

    A value below 1 falls back to the default.
    """
    raw = getattr(settings, "PYMISSIVE_SEND_CHUNK_SIZE", SEND_CHUNK_SIZE_DEFAULT)
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return SEND_CHUNK_SIZE_DEFAULT
    if size < 1:
        return SEND_CHUNK_SIZE_DEFAULT
    return size


def get_progress_hooks(hook=None):
    """Resolve a progress hook to a list of callables.

    ``hook`` defaults to ``settings.PYMISSIVE_PROGRESS_HOOK``. Pass a value
    to override the setting (the scheduler's ``progress_hook`` field).

    Unset, ``None`` or empty → ``[]``: the send loop does not notify. The
    progress page still reads live counts.

    A single dotted import path or callable becomes a one-item list. A
    list or tuple of paths and/or callables is resolved in order. Each hook
    receives the scheduled campaign.
    """
    if hook is None:
        hook = getattr(settings, "PYMISSIVE_PROGRESS_HOOK", None)
    if not hook:
        return []
    if isinstance(hook, (list, tuple)):
        return [_resolve_hook(item) for item in hook]
    return [_resolve_hook(hook)]


#: Support → (model field, key in ``PYMISSIVE_DEFAULT_SENDER``).
SENDER_CONTACT_FIELDS = {
    "email": ("sender_email", "email"),
    "phone": ("sender_phone", "phone"),
    "address": ("sender_address", "address"),
}

CAMPAIGN_SENDER_NAME_FIELDS = (
    "sender_email_name",
    "sender_phone_name",
    "sender_address_name",
)


def get_default_sender() -> dict:
    """Return ``settings.PYMISSIVE_DEFAULT_SENDER`` (name / email / phone / address)."""
    raw = getattr(settings, "PYMISSIVE_DEFAULT_SENDER", None)
    return dict(raw) if isinstance(raw, dict) else {}


def is_empty_sender_value(value) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, dict) and not any(value.values()):
        return True
    return False


def apply_default_sender_fields(instance, fields: dict) -> None:
    """Fill empty *instance* attributes from ``PYMISSIVE_DEFAULT_SENDER``.

    *fields* maps attribute name → setting key (``name``, ``email``, …).
    Already-set values are left untouched.
    """
    defaults = get_default_sender()
    if not defaults:
        return
    for attr, key in fields.items():
        if not hasattr(instance, attr) or not is_empty_sender_value(getattr(instance, attr, None)):
            continue
        value = defaults.get(key)
        if value in (None, "", {}, []):
            continue
        setattr(instance, attr, value)


#: Seconds without a scheduler heartbeat before a ``PROCESSING`` missive or
#: an open run is treated as dead (worker crash / SIGKILL). ``<= 0`` disables.
STALE_PROCESSING_SECONDS_DEFAULT = 30 * 60


def stale_processing_seconds() -> int:
    """Return ``settings.PYMISSIVE_STALE_PROCESSING_SECONDS`` (default 1800)."""
    return int(getattr(settings, "PYMISSIVE_STALE_PROCESSING_SECONDS", STALE_PROCESSING_SECONDS_DEFAULT))


def stale_processing_cutoff():
    """Return the datetime before which a heartbeat is considered stale.

    ``None`` when the timeout is disabled (``<= 0``).
    """
    seconds = stale_processing_seconds()
    if seconds <= 0:
        return None
    return timezone.now() - timedelta(seconds=seconds)


def is_dry_run() -> bool:
    """Return True when dry-run mode is enabled (test/staging).

    Controlled by ``settings.PYMISSIVE_DRY_RUN``. Defaults to False (real sends).

    When enabled, ``Missive.send_missive`` and ``Missive.prepare_missive``:

    - run the full local pipeline (campaign inheritance, body processors,
      first_document PDF generation, ``get_serialized_data``);
    - skip the provider call entirely;
    - persist a synthetic ``external_id`` prefixed with ``dry-run:``;
    - record a ``SUBMITTED`` event with ``trace={"dry_run": True, ...}`` so
      tests can assert the missive went through the pipeline.
    """
    return bool(getattr(settings, "PYMISSIVE_DRY_RUN", False))


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped.

    Delegates to :func:`pymissive.utils.is_disable_send` (Django setting or env).

    Unlike dry-run mode, providers still run every preparation/staging step;
    only the final confirmation network call is skipped. Django persists the
    provider ``disabled_send`` response via ``Missive._disabled_send``.
    """
    from pymissive.utils import is_disable_send as _is_disable_send

    return _is_disable_send()

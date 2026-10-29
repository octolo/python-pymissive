"""Utility functions for django_pymissive."""

import json
import logging
import os
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import FieldError, ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from .models.choices import MissiveRecipientType
from .models.recipient import MissiveRecipient

logger = logging.getLogger(__name__)

SNAPSHOT_HTML_READ_MORE_LENGTH = 500


def serialize_model_for_context(obj) -> dict:
    """Plain dict for templates (no live model — avoids callable access like ``delete()``)."""
    data = {field.attname: field.value_from_object(obj) for field in obj._meta.concrete_fields}
    if callable(getattr(obj, "to_context_dict", None)):
        data.update(obj.to_context_dict())
    return data


def snapshot_html_read_more(value: str | None) -> str:
    """Return an HTML-balanced excerpt of a rich-text snapshot."""
    if not value:
        return ""
    configured_length = getattr(
        settings,
        "PYMISSIVE_SNAPSHOT_HTML_READ_MORE_LENGTH",
        SNAPSHOT_HTML_READ_MORE_LENGTH,
    )
    try:
        length = max(1, int(configured_length))
    except (TypeError, ValueError):
        length = SNAPSHOT_HTML_READ_MORE_LENGTH
    return Truncator(value).chars(length, html=True)


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
    domain = getattr(settings, "PYMISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None) or "localhost:8000"
    domain = str(domain).strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        return parsed.netloc or domain
    return domain


def get_default_scheme():
    """Return default scheme from settings (PYMISSIVE_SCHEME, SCHEME) or http.
    If domain setting is a full URL, extracts scheme from it.
    """
    scheme = getattr(settings, "PYMISSIVE_SCHEME", None) or getattr(settings, "SCHEME", None)
    if scheme:
        return str(scheme).replace("://", "")
    domain = getattr(settings, "PYMISSIVE_DOMAIN", None) or getattr(settings, "DOMAIN", None)
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


_RECIPIENT_GROUPS = ("recipients", "cc", "bcc", "notification")
_CONTACT_FIELD = {
    "email": "email",
    "phone": "phone",
    "address": "address",
    "application": "notification_id",
}
_ABSENT = object()


def _is_processor_path(value) -> bool:
    return isinstance(value, str) and "." in value and "@" not in value and " " not in value


def _call_if_processor(value):
    """Call a dotted path or callable. Emails and plain contacts stay as they are."""
    if callable(value):
        return value()
    if _is_processor_path(value):
        return import_allowed_string(value)()
    return value


def _expand_allowed(value) -> list:
    """Allow-list entries: contacts, or a processor that returns contacts."""
    value = _call_if_processor(value)
    if isinstance(value, (list, tuple, set)):
        items: list = []
        for item in value:
            resolved = _call_if_processor(item)
            if isinstance(resolved, (list, tuple, set)):
                items.extend(resolved)
            else:
                items.append(resolved)
        return items
    return [value]


def _channel_setting(name: str, missive_type: str):
    """Value for this missive type, or ``_ABSENT`` when the channel is not configured.

    A missive-type key (``sms``, ``letter``) wins over the support key
    (``phone``, ``address``). ``PYMISSIVE_RECIPIENT_ALLOWED`` may be a dotted
    path or a callable: a dict is read like the setting, a list is the email
    allow-list.
    """
    from pymissive.config import missive_support_for_type, normalize_missive_type

    canonical = normalize_missive_type(missive_type) or str(missive_type or "").strip().lower()
    support = missive_support_for_type(canonical)
    field = _CONTACT_FIELD.get(support)
    if not field:
        return None, _ABSENT
    raw = getattr(settings, name, None)
    if name == "PYMISSIVE_RECIPIENT_ALLOWED":
        raw = _call_if_processor(raw)
        if isinstance(raw, (list, tuple, set)):
            if field == "email":
                return field, list(raw)
            return field, _ABSENT
    if not isinstance(raw, dict):
        return field, _ABSENT
    if canonical in raw:
        return field, raw[canonical]
    if support in raw:
        return field, raw[support]
    return field, _ABSENT


def _blank_override(value) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return isinstance(value, (list, tuple))


def _contact_key(value, field: str) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    text = str(value or "").strip()
    if field == "email":
        return text.casefold()
    if field == "phone":
        return "".join(ch for ch in text if ch.isdigit() or ch == "+")
    return text


def apply_send_recipients(payload: dict, missive_type: str, *, log: bool = True) -> dict:
    """Rewrite recipients for this send only. Stored rows are left untouched.

    ``PYMISSIVE_RECIPIENT_ALLOWED`` lists the contacts that may keep their
    real address. A channel value, or the whole setting, may be a dotted path
    or a callable that returns that list. Anyone else is replaced by
    ``PYMISSIVE_OVERRIDE_RECIPIENT`` for the same missive type (or its
    support). When that override is empty, the send is refused.
    """
    field, override = _channel_setting("PYMISSIVE_OVERRIDE_RECIPIENT", missive_type)
    allowed_field, allowed = _channel_setting("PYMISSIVE_RECIPIENT_ALLOWED", missive_type)
    if field is None or (override is _ABSENT and allowed is _ABSENT):
        return payload
    contact_field = field or allowed_field
    allowed_keys = None
    if allowed is not _ABSENT:
        allowed_keys = {
            _contact_key(item, contact_field) for item in _expand_allowed(allowed) if not _blank_override(item)
        }
    override_value = None if override is _ABSENT or _blank_override(override) else override
    refused = []
    replaced = []
    rewritten = dict(payload)
    for group in _RECIPIENT_GROUPS:
        rows = rewritten.get(group)
        if not isinstance(rows, list) or not rows:
            continue
        updated = []
        for row in rows:
            if not isinstance(row, dict):
                updated.append(row)
                continue
            current = row.get(contact_field)
            if allowed_keys is not None and _contact_key(current, contact_field) in allowed_keys:
                updated.append(row)
                continue
            if override_value is not None:
                updated.append({**row, contact_field: override_value})
                replaced.append(f"{group} {current} -> {override_value}")
                continue
            if allowed_keys is not None:
                refused.append(str(current or ""))
                continue
            updated.append(row)
        rewritten[group] = updated
    if log and replaced:
        logger.warning(
            "PYMISSIVE_OVERRIDE_RECIPIENT replaced %s recipient(s) for %s: %s",
            len(replaced),
            missive_type,
            "; ".join(replaced),
        )
    if refused:
        raise ValidationError(
            _("Recipient %(contacts)s is not allowed for %(missive_type)s and PYMISSIVE_OVERRIDE_RECIPIENT is empty.")
            % {"contacts": ", ".join(refused), "missive_type": missive_type}
        )
    return rewritten


def _dry_run_setting():
    raw = getattr(settings, "PYMISSIVE_DRY_RUN", False)
    if isinstance(raw, str):
        return raw.strip().lower()
    return raw


def disallowed_recipients(groups: dict, missive_type: str) -> list[str]:
    """Contacts that must not leave the process for this missive type.

    An empty list means every contact is on ``PYMISSIVE_RECIPIENT_ALLOWED``.
    Without an allow-list for the channel, the result is ``["no allow-list"]``.
    """
    field, allowed = _channel_setting("PYMISSIVE_RECIPIENT_ALLOWED", missive_type)
    if field is None or allowed is _ABSENT:
        return ["no allow-list"]
    allowed_keys = {_contact_key(item, field) for item in _expand_allowed(allowed) if not _blank_override(item)}
    blocked = []
    for group in _RECIPIENT_GROUPS:
        rows = groups.get(group) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                blocked.append(str(row))
                continue
            current = row.get(field)
            if _contact_key(current, field) not in allowed_keys:
                blocked.append(str(current or ""))
    return blocked


def dry_run_block(groups: dict, missive_type: str) -> list[str] | None:
    """Contacts forcing a dry-run, or ``None`` when the provider may be called.

    ``PYMISSIVE_DRY_RUN`` True → ``[]``. ``"allowed"`` → the contacts outside
    ``PYMISSIVE_RECIPIENT_ALLOWED`` (or ``["no allow-list"]``). Any other value
    → ``None``.
    """
    if is_dry_run():
        return []
    if _dry_run_setting() != "allowed":
        return None
    blocked = disallowed_recipients(groups, missive_type)
    if not blocked:
        return None
    logger.warning(
        "PYMISSIVE_DRY_RUN=allowed skipped the provider for %s: %s",
        missive_type,
        ", ".join(blocked),
    )
    return blocked


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
    """Return True when every send stays local (test/staging).

    ``settings.PYMISSIVE_DRY_RUN``:

    - ``True`` — skip the provider for every missive;
    - ``False`` — call the provider;
    - ``"allowed"`` — call the provider only when every recipient is on
      ``PYMISSIVE_RECIPIENT_ALLOWED``. One contact outside that list keeps
      the whole missive local. That case is not reported here; send uses
      :func:`dry_run_block`.

    A full dry-run still runs the local pipeline, stores a ``dry-run:``
    ``external_id``, and records ``trace={"dry_run": True, ...}``.
    """
    raw = _dry_run_setting()
    if raw == "allowed":
        return False
    return bool(raw)


def is_force_fake_provider() -> bool:
    """Return True when every missive must use the local ``fake`` provider.

    ``settings.PYMISSIVE_FORCE_FAKE_PROVIDER`` (or the same environment
    variable). Unlike dry-run, the provider is still called: it is ``fake``,
    so nothing leaves the process. A provider already stored on the missive,
    and the per-type default, are replaced. Dry-run still skips that call.
    """
    from pymissive.utils import is_force_fake_provider as _is_force_fake_provider

    return _is_force_fake_provider()


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped.

    Delegates to :func:`pymissive.utils.is_disable_send` (Django setting or env).

    Unlike dry-run mode, providers still run every preparation/staging step;
    only the final confirmation network call is skipped. Django persists the
    provider ``disabled_send`` response via ``Missive._disabled_send``.
    """
    from pymissive.utils import is_disable_send as _is_disable_send

    return _is_disable_send()

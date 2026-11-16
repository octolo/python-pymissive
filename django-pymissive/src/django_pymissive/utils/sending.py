"""Sending policy and runtime-setting helpers."""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .imports import _resolve_hook, import_allowed_string

logger = logging.getLogger(__name__)


PROGRESS_STEP_DEFAULT = 20

SEND_CHUNK_SIZE_DEFAULT = 500

SENDER_CONTACT_FIELDS = {
    "email": ("sender_email", "email"),
    "phone": ("sender_phone", "phone"),
    "address": ("sender_address", "address"),
}

_RECIPIENT_GROUPS = ("recipients", "cc", "bcc", "notification")

_CONTACT_FIELD = {
    "email": "email",
    "phone": "phone",
    "address": "address",
    "application": "notification_id",
}

_ABSENT = object()

STALE_PROCESSING_SECONDS_DEFAULT = 30 * 60


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


def sender_default_fields(support: str | None) -> dict[str, str]:
    """Map sender attributes to ``PYMISSIVE_DEFAULT_SENDER`` keys for one support."""
    fields = {"sender_name": "name"}
    mapping = SENDER_CONTACT_FIELDS.get((support or "").lower())
    if mapping:
        attr, key = mapping
        fields[attr] = key
    return fields


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


def _allowed_contact_keys(allowed, field: str) -> set[str] | None:
    if allowed is _ABSENT:
        return None
    return {_contact_key(item, field) for item in _expand_allowed(allowed) if not _blank_override(item)}


def _rewrite_recipient_rows(rows, field, allowed_keys, override_value):
    updated = []
    refused = []
    replaced = []
    for row in rows:
        if not isinstance(row, dict):
            updated.append(row)
            continue
        current = row.get(field)
        if allowed_keys is not None and _contact_key(current, field) in allowed_keys:
            updated.append(row)
        elif override_value is not None:
            updated.append({**row, field: override_value})
            replaced.append(f"{current} -> {override_value}")
        elif allowed_keys is not None:
            refused.append(str(current or ""))
        else:
            updated.append(row)
    return updated, refused, replaced


def _recipient_send_policy(missive_type):
    field, override = _channel_setting("PYMISSIVE_OVERRIDE_RECIPIENT", missive_type)
    allowed_field, allowed = _channel_setting("PYMISSIVE_RECIPIENT_ALLOWED", missive_type)
    if field is None or (override is _ABSENT and allowed is _ABSENT):
        return None
    contact_field = field or allowed_field
    allowed_keys = _allowed_contact_keys(allowed, contact_field)
    override_value = None if override is _ABSENT or _blank_override(override) else override
    return contact_field, allowed_keys, override_value


def apply_send_recipients(payload: dict, missive_type: str, *, log: bool = True) -> dict:
    """Rewrite recipients for this send only. Stored rows are left untouched.

    ``PYMISSIVE_RECIPIENT_ALLOWED`` lists the contacts that may keep their
    real address. A channel value, or the whole setting, may be a dotted path
    or a callable that returns that list. Anyone else is replaced by
    ``PYMISSIVE_OVERRIDE_RECIPIENT`` for the same missive type (or its
    support). When that override is empty, the send is refused.
    """
    policy = _recipient_send_policy(missive_type)
    if policy is None:
        return payload
    contact_field, allowed_keys, override_value = policy
    refused: list[str] = []
    replaced: list[str] = []
    rewritten = dict(payload)
    for group in _RECIPIENT_GROUPS:
        rows = rewritten.get(group)
        if not isinstance(rows, list) or not rows:
            continue
        updated, group_refused, group_replaced = _rewrite_recipient_rows(
            rows,
            contact_field,
            allowed_keys,
            override_value,
        )
        rewritten[group] = updated
        refused.extend(group_refused)
        replaced.extend(f"{group} {replacement}" for replacement in group_replaced)
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


def _disallowed_recipient_rows(rows, field, allowed_keys):
    blocked = []
    for row in rows:
        if not isinstance(row, dict):
            blocked.append(str(row))
            continue
        current = row.get(field)
        if _contact_key(current, field) not in allowed_keys:
            blocked.append(str(current or ""))
    return blocked


def disallowed_recipients(groups: dict, missive_type: str) -> list[str]:
    """Contacts that must not leave the process for this missive type.

    An empty list means every contact is on ``PYMISSIVE_RECIPIENT_ALLOWED``.
    Without an allow-list for the channel, the result is ``["no allow-list"]``.
    """
    field, allowed = _channel_setting("PYMISSIVE_RECIPIENT_ALLOWED", missive_type)
    if field is None or allowed is _ABSENT:
        return ["no allow-list"]
    allowed_keys = _allowed_contact_keys(allowed, field)
    blocked = []
    for group in _RECIPIENT_GROUPS:
        rows = groups.get(group) or []
        if not isinstance(rows, list):
            continue
        blocked.extend(_disallowed_recipient_rows(rows, field, allowed_keys))
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
    return isinstance(value, dict) and not any(value.values())


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


def forced_provider_name() -> str:
    """Return the configured provider override, empty when disabled."""
    from pymissive.utils import forced_provider_name as _forced_provider_name

    return _forced_provider_name()


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped.

    Delegates to :func:`pymissive.utils.is_disable_send` (Django setting or env).

    Unlike dry-run mode, providers still run every preparation/staging step;
    only the final confirmation network call is skipped. Django persists the
    provider ``disabled_send`` response via ``Missive._disabled_send``.
    """
    from pymissive.utils import is_disable_send as _is_disable_send

    return _is_disable_send()

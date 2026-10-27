"""Build the draft missive of one campaign target. Sending is a later step.

The chain uses the same entry format as the other processors. The built-in
:func:`build_target_processor` reads the target through
``settings.PYMISSIVE_BUILD_TARGET_FIELDS``: ``name`` for the recipient name,
then the contact key of the channel (``email``, ``phone``, ``address``,
``notification_id``). ``full_targets`` also reads the plural key (``emails``,
``phones``, ``addresses``, ``notification_ids``) and adds one recipient per
value. The target is stored on the missive as a related object
(``content_type`` + ``object_id``).
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from ..utils import import_allowed_string


DEFAULT_BUILD_TARGET_PROCESSORS: list = [
    "django_pymissive.processors.build_target.build_target_processor",
]

#: Attribute names tried on the target, in order.
#: ``name`` keeps the first non-empty value. A channel reads its singular key,
#: then the plural key when ``full_targets`` is set.
#: Overridden per key by ``settings.PYMISSIVE_BUILD_TARGET_FIELDS``.
DEFAULT_BUILD_TARGET_FIELDS = {
    "name": ("full_name", "name"),
    "email": ("email",),
    "emails": ("emails",),
    "phone": ("phone",),
    "phones": ("phones",),
    "address": ("address",),
    "addresses": ("addresses",),
    "notification_id": ("notification_id",),
    "notification_ids": ("notification_ids",),
}

#: Support key, then the plural key used when ``full_targets`` is set.
_SUPPORT_KEYS = {
    "email": ("email", "emails"),
    "phone": ("phone", "phones"),
    "address": ("address", "addresses"),
    "application": ("notification_id", "notification_ids"),
}

#: Field stored on the missive recipient. Independent of the target attribute.
_RECIPIENT_FIELD = {
    "email": "email",
    "phone": "phone",
    "address": "address",
    "application": "notification_id",
}

_RECIPIENT_MODELS = {
    "email": "MissiveRecipientEmail",
    "phone": "MissiveRecipientPhone",
    "address": "MissiveRecipientAddress",
    "application": "MissiveRecipientApplication",
}


def get_default_build_target_processors() -> list:
    """Return the default build-target chain.

    Honors ``settings.PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS`` when set.
    A bare dotted path is accepted as a one-entry chain.
    """
    override = getattr(settings, "PYMISSIVE_DEFAULT_BUILD_TARGET_PROCESSORS", None)
    if override is None:
        return list(DEFAULT_BUILD_TARGET_PROCESSORS)
    if isinstance(override, str):
        return [override]
    return list(override)


def build_from_processors(processors):
    """Return ``build(campaign, target, missive_type)`` for *processors*."""

    def build(campaign, target, missive_type):
        return apply_build_target_processors(
            campaign,
            target,
            missive_type,
            processors,
        )

    return build


def apply_build_target_processors(campaign, target, missive_type, processors):
    """Run *processors* until one returns a missive. None of them send it."""
    for entry in processors or []:
        if entry is None:
            continue
        processor, extra_kwargs = _resolve_processor(entry)
        result = _call_processor(
            processor,
            campaign,
            target,
            missive_type,
            **extra_kwargs,
        )
        if result is not None:
            return result
    return None


def build_target_processor(
    campaign,
    target,
    missive_type,
    *,
    full_targets=None,
    extra_missive_fields=None,
):
    """Create one draft missive for *target*. Does not send it.

    *full_targets* defaults to ``settings.PYMISSIVE_BUILD_TARGET_FULL``
    (false). The singular key of the channel is always read. The plural key
    is added only when *full_targets* is true. Attribute names come from
    :func:`build_target_fields`.
    """
    from pymissive.config import missive_support_for_type

    from ..services.drafts import build_draft

    if full_targets is None:
        full_targets = bool(getattr(settings, "PYMISSIVE_BUILD_TARGET_FULL", False))
    support = missive_support_for_type(missive_type)
    keys = _SUPPORT_KEYS.get(support)
    if keys is None:
        return None
    singular_key, plural_key = keys
    fields = build_target_fields()
    values = _contact_values(
        target,
        fields.get(singular_key, ()),
        fields.get(plural_key, ()),
        full_targets=full_targets,
    )
    if not values:
        return None
    name = _target_name(target, fields.get("name", ()))
    missive = build_draft(
        campaign,
        target,
        missive_type,
        name=name,
        extra_missive_fields=extra_missive_fields,
        **{_RECIPIENT_FIELD[support]: values[0]},
    )
    if missive is None:
        return None
    for value in values[1:]:
        _add_recipient(missive, support, name, value)
    return missive


def build_target_fields() -> dict[str, tuple[str, ...]]:
    """Return the target attributes to read, one tuple of names per key.

    ``settings.PYMISSIVE_BUILD_TARGET_FIELDS`` replaces a key when it lists at
    least one name. Keys left out keep :data:`DEFAULT_BUILD_TARGET_FIELDS`.
    A string is accepted as a single name.
    """
    merged = {key: tuple(names) for key, names in DEFAULT_BUILD_TARGET_FIELDS.items()}
    raw = getattr(settings, "PYMISSIVE_BUILD_TARGET_FIELDS", None)
    if not isinstance(raw, dict):
        return merged
    for key, names in raw.items():
        parsed = _as_field_names(names)
        if parsed:
            merged[str(key)] = parsed
    return merged


def _as_field_names(names) -> tuple[str, ...]:
    if isinstance(names, str):
        name = names.strip()
        return (name,) if name else ()
    if not names:
        return ()
    return tuple(str(name).strip() for name in names if str(name or "").strip())


def _target_name(target, field_names) -> str:
    for field in field_names:
        value = getattr(target, field, None)
        if callable(value) or value in (None, ""):
            continue
        return str(value)
    return ""


def _contact_values(target, singular, plural, *, full_targets: bool) -> list:
    names = list(singular)
    if full_targets:
        names.extend(plural)
    values = []
    seen = set()
    for name in names:
        for value in _as_values(getattr(target, name, None)):
            key = _dedupe_key(value)
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
    return values


def _as_values(raw) -> list:
    if raw in (None, "", {}, []):
        return []
    if isinstance(raw, (str, dict)):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        return [item for item in raw if item not in (None, "", {})]
    return [raw]


def _dedupe_key(value) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _add_recipient(missive, support: str, name: str, value) -> None:
    from ..models import recipient as recipient_models

    model = getattr(recipient_models, _RECIPIENT_MODELS[support])
    model.objects.create(
        missive=missive,
        name=name,
        **{_RECIPIENT_FIELD[support]: value},
    )


def _resolve_processor(processor: Any) -> tuple[Any, dict]:
    extra_kwargs: dict = {}
    if isinstance(processor, dict):
        path = processor.get("processor") or processor.get("path")
        extra_kwargs = dict(processor.get("kwargs") or {})
        processor = path
    elif isinstance(processor, (list, tuple)) and len(processor) == 2:
        processor, extra_kwargs = processor[0], dict(processor[1] or {})

    if isinstance(processor, str):
        processor = import_allowed_string(processor)
    if isinstance(processor, type):
        processor = processor()
    return processor, extra_kwargs


def _call_processor(processor, campaign, target, missive_type, **kwargs):
    if hasattr(processor, "process") and callable(processor.process):
        return processor.process(campaign, target, missive_type, **kwargs)
    if callable(processor):
        return processor(campaign, target, missive_type, **kwargs)
    raise TypeError(f"Build target processor {processor!r} is not callable and has no .process() method")

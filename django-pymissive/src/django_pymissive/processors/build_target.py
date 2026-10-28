"""Build the draft missive of one campaign target. Sending is a later step.

The chain uses the same entry format as the other processors. The built-in
:func:`build_target_processor` reads the target through
``settings.PYMISSIVE_BUILD_TARGET_FIELDS``: ``name`` for the recipient name,
then the contact key of the channel (``email``, ``phone``, ``address``,
``notification_id``). ``full_targets`` also reads the plural key (``emails``,
``phones``, ``addresses``, ``notification_ids``) and adds one recipient per
value. The target is stored on the missive as a related object
(``content_type`` + ``object_id``).

Optional campaign sub-targets split those values by recipient type. With
none, every contact of the channel is a recipient.
"""

from __future__ import annotations

import inspect
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

#: Role of the contacts read from the object, one per channel support.
#: A sub-target replaces the list of its own role. Sending still requires
#: at least one ``recipient``, so every support defaults to that role.
_DEFAULT_RECIPIENT_TYPE = {
    "email": "recipient",
    "phone": "recipient",
    "address": "recipient",
    "application": "recipient",
}

_RECIPIENT_TYPE_ORDER = ("recipient", "cc", "bcc", "notification")


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


def build_from_processors(processors, *, row=None):
    """Return ``build(campaign, target, missive_type)`` for *processors*.

    *row*, when given, is the selection already loaded with its contacts.
    A processor that declares ``row`` or accepts ``**kwargs`` receives it.
    """

    def build(campaign, target, missive_type):
        return apply_build_target_processors(
            campaign,
            target,
            missive_type,
            processors,
            row=row,
        )

    return build


def apply_build_target_processors(campaign, target, missive_type, processors, *, row=None):
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
            row=row,
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
    row=None,
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
    if support not in _SUPPORT_KEYS:
        return None
    grouped = resolve_target_recipients(
        campaign,
        target,
        missive_type,
        full_targets=full_targets,
        row=row,
    )
    grouped = _usable_grouped_contacts(grouped, support)
    primary_type = default_recipient_type(missive_type)
    if not grouped.get(primary_type):
        return None
    ordered = _ordered_contacts(grouped, primary_type)
    fallback_name = _target_name(target, build_target_fields().get("name", ()))
    first_type, first_value = ordered[0]
    first_name, first_contact = _split_contact(first_value, support, fallback_name)
    missive = build_draft(
        campaign,
        target,
        missive_type,
        name=first_name,
        recipient_type=first_type,
        extra_missive_fields=extra_missive_fields,
        **{_RECIPIENT_FIELD[support]: first_contact},
    )
    if missive is None:
        return None
    for recipient_type, value in ordered[1:]:
        item_name, contact = _split_contact(value, support, fallback_name)
        _add_recipient(missive, support, item_name, contact, recipient_type=recipient_type)
    return missive


def default_recipient_type(missive_type: str) -> str:
    """Recipient role of the contacts the channel reads on the object.

    Email, phone, postal and application contacts are recipients. A
    sub-target is what moves a list to cc, bcc or notification.
    """
    from pymissive.config import missive_support_for_type

    from ..models.choices import MissiveRecipientType

    support = missive_support_for_type(missive_type)
    return _DEFAULT_RECIPIENT_TYPE.get(support, MissiveRecipientType.RECIPIENT)


def contacts_of_target(row) -> list:
    """Contacts *row* will use, in send order.

    Same rules as :func:`resolve_target_recipients`, with full targets read
    from ``settings.PYMISSIVE_BUILD_TARGET_FULL``. The result is a new list.
    """
    from pymissive.config import missive_support_for_type

    full_targets = bool(getattr(settings, "PYMISSIVE_BUILD_TARGET_FULL", False))
    grouped = resolve_target_recipients(
        getattr(row, "campaign", None),
        _linked_object(row),
        row.missive_type,
        full_targets=full_targets,
        row=row,
    )
    grouped = _usable_grouped_contacts(grouped, missive_support_for_type(row.missive_type))
    ordered = _ordered_contacts(grouped, default_recipient_type(row.missive_type))
    return [value for _recipient_type, value in ordered]


def resolve_target_recipients(
    campaign,
    target,
    missive_type,
    *,
    full_targets: bool = False,
    row=None,
) -> dict[str, list]:
    """Contacts grouped by recipient type.

    *row*, when given, is the selection whose sub-targets are read.
    Otherwise the live row of *target* on this channel is used. Each
    sub-target owns its role, even with an empty list, so a contact can
    be left out. Every other contact of the channel goes to
    :func:`default_recipient_type`.
    """
    from pymissive.config import missive_support_for_type

    if row is None:
        from ..models.campaign_target import active_campaign_target

        row = active_campaign_target(campaign, target, missive_type)
    grouped: dict[str, list] = {}
    owned: set[str] = set()
    if row is not None and row.pk:
        for sub in row.to_campaignrecipienttarget.all():
            owned.add(sub.recipient_type)
            values = _deduped(sub.values)
            if values:
                grouped[sub.recipient_type] = values
    default_type = default_recipient_type(missive_type)
    if default_type in owned or target is None:
        return grouped
    support = missive_support_for_type(missive_type)
    keys = _SUPPORT_KEYS.get(support)
    if keys is None:
        return grouped
    singular_key, plural_key = keys
    fields = build_target_fields()
    values = _contact_values(
        target,
        fields.get(singular_key, ()),
        fields.get(plural_key, ()),
        full_targets=full_targets,
    )
    if values:
        grouped[default_type] = values
    return grouped


def contacts_for_channel(target, missive_type, *, first: bool = False) -> list:
    """Contacts of *missive_type* read on *target*.

    ``first`` reads the singular attribute only (``email``, ``phone``,
    ``address``, ``notification_id``): the first contact. Otherwise the
    plural attribute is read (``emails``, ``phones``, ``addresses``,
    ``notification_ids``): the whole set. Names come from
    :func:`build_target_fields`.
    """
    from pymissive.config import missive_support_for_type

    support = missive_support_for_type(missive_type)
    keys = _SUPPORT_KEYS.get(support)
    if keys is None or target is None:
        return []
    singular_key, plural_key = keys
    fields = build_target_fields()
    if first:
        return _contact_values(target, fields.get(singular_key, ()), (), full_targets=False)
    return _contact_values(target, (), fields.get(plural_key, ()), full_targets=True)


def contact_identity(value, missive_type: str) -> str:
    """Stable key of one stored contact on this channel."""
    from pymissive.config import missive_support_for_type

    support = missive_support_for_type(missive_type)
    field = _RECIPIENT_FIELD.get(support)
    if isinstance(value, dict) and field and field in value:
        value = value[field]
    if value in (None, "", {}):
        return ""
    return _dedupe_key(value)


def _split_contact(value, support: str, fallback_name: str) -> tuple[str, object]:
    """Return ``(name, channel value)`` for a stored contact.

    A dict that carries the channel field (``email``, ``phone``, ``address``,
    ``notification_id``) is a chosen recipient. Anything else is the channel
    value itself, with the target's name.
    """
    field = _RECIPIENT_FIELD[support]
    if isinstance(value, dict) and field in value:
        name = value.get("name") or fallback_name
        return str(name or ""), value[field]
    return fallback_name, value


def _usable_grouped_contacts(grouped: dict[str, list], support: str) -> dict[str, list]:
    result = {}
    for recipient_type, values in grouped.items():
        usable = [value for value in values if _is_usable_contact(value, support)]
        if usable:
            result[recipient_type] = usable
    return result


def _is_usable_contact(value, support: str) -> bool:
    field = _RECIPIENT_FIELD.get(support)
    if field is None:
        return False
    if isinstance(value, dict):
        if field in value:
            value = value[field]
        elif support != "address":
            return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(item not in (None, "", {}, []) for item in value.values())
    return value not in (None, "", {}, [])


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


def _linked_object(row):
    if not getattr(row, "content_type_id", None) or not row.object_id:
        return None
    try:
        return row.target
    except Exception:
        return None


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


def _ordered_contacts(grouped: dict[str, list], default_type: str) -> list[tuple[str, object]]:
    types = [default_type]
    types.extend(recipient_type for recipient_type in _RECIPIENT_TYPE_ORDER if recipient_type not in types)
    types.extend(recipient_type for recipient_type in grouped if recipient_type not in types)
    return [(recipient_type, value) for recipient_type in types for value in grouped.get(recipient_type, ())]


def _deduped(raw) -> list:
    values = []
    seen = set()
    for value in _as_values(raw):
        key = _dedupe_key(value)
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def _add_recipient(missive, support: str, name: str, value, *, recipient_type: str) -> None:
    from ..models import recipient as recipient_models

    model = getattr(recipient_models, _RECIPIENT_MODELS[support])
    model.objects.create(
        missive=missive,
        name=name,
        recipient_type=recipient_type,
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
    row = kwargs.pop("row", None)
    if hasattr(processor, "process") and callable(processor.process):
        if row is not None and _accepts_keyword(processor.process, "row"):
            kwargs["row"] = row
        return processor.process(campaign, target, missive_type, **kwargs)
    if callable(processor):
        if row is not None and _accepts_keyword(processor, "row"):
            kwargs["row"] = row
        return processor(campaign, target, missive_type, **kwargs)
    raise TypeError(f"Build target processor {processor!r} is not callable and has no .process() method")


def _accepts_keyword(processor, name: str) -> bool:
    try:
        parameters = inspect.signature(processor).parameters
    except (TypeError, ValueError):
        return False
    parameter = parameters.get(name)
    if parameter is not None and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY:
        return True
    return any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())

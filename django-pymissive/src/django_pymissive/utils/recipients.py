"""Recipient lookup helpers."""

from django.core.exceptions import FieldError, ValidationError

from ..models.choices import MissiveRecipientType
from ..models.recipient import MissiveRecipient


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

    Do not pass the whole dict to ``.get(**data)``: provider events may carry
    ``custom_id`` (often a UUID from another system) as ``id``, while
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

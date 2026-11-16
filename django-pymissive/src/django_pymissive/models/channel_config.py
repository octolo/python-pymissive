"""Channel payload shared by a campaign step and the missive built from it.

The tuples are the single description of which values a missive can inherit.
They are not model fields: ``CampaignStep`` and ``Missive`` keep their own
columns because nullability and defaults differ.
"""

from __future__ import annotations

from pymissive.config import missive_support_for_type


def _fields(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for group in groups for name in group)


SUBJECT = ("subject",)
SENDER_NAME = ("sender_name",)
BODY_TEXT = ("body_text",)
BRAND_NAME = ("brand_name",)
RICH_BODY_FIELDS = ("body_rich", "body_rich_snapshot_html")
EMAIL_CONTACT_FIELDS = ("sender_name", "sender_email", "reply_to_name", "reply_to_email")
PHONE_CONTACT_FIELDS = ("sender_name", "sender_phone")
POSTAL_SENDER_FIELDS = ("sender_name", "sender_address")
POSTAL_REPLY_FIELDS = ("reply_to_name", "reply_to_address")
POSTAL_PRINTING_FIELDS = ("duplex_printing", "color_printing")

CAMPAIGN_SOURCED_FIELDS: dict[str, tuple[str, ...]] = {
    "email": _fields(SUBJECT, RICH_BODY_FIELDS, BODY_TEXT, EMAIL_CONTACT_FIELDS),
    "phone": _fields(SUBJECT, BODY_TEXT, PHONE_CONTACT_FIELDS),
    "application": _fields(SUBJECT, RICH_BODY_FIELDS, BODY_TEXT, SENDER_NAME, BRAND_NAME),
    "address": _fields(
        SUBJECT,
        RICH_BODY_FIELDS,
        BODY_TEXT,
        POSTAL_PRINTING_FIELDS,
        POSTAL_SENDER_FIELDS,
        POSTAL_REPLY_FIELDS,
    ),
}

ADMIN_MISSIVE_TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "email": _fields(SUBJECT, EMAIL_CONTACT_FIELDS, BODY_TEXT, RICH_BODY_FIELDS),
    "email_marketing": _fields(SUBJECT, EMAIL_CONTACT_FIELDS, BODY_TEXT, RICH_BODY_FIELDS),
    "ere": _fields(SUBJECT, EMAIL_CONTACT_FIELDS, BODY_TEXT, RICH_BODY_FIELDS),
    "sms": _fields(PHONE_CONTACT_FIELDS, BODY_TEXT),
    "rcs": _fields(PHONE_CONTACT_FIELDS, BODY_TEXT),
    "voice_call": _fields(PHONE_CONTACT_FIELDS, BODY_TEXT),
    "letter": _fields(
        POSTAL_SENDER_FIELDS,
        POSTAL_REPLY_FIELDS,
        POSTAL_PRINTING_FIELDS,
        RICH_BODY_FIELDS,
    ),
    "registered_letter": _fields(
        POSTAL_SENDER_FIELDS,
        POSTAL_REPLY_FIELDS,
        POSTAL_PRINTING_FIELDS,
        RICH_BODY_FIELDS,
    ),
    "hand_delivery": _fields(
        POSTAL_SENDER_FIELDS,
        POSTAL_REPLY_FIELDS,
        POSTAL_PRINTING_FIELDS,
        RICH_BODY_FIELDS,
    ),
    "notification": _fields(SUBJECT, SENDER_NAME, BODY_TEXT, RICH_BODY_FIELDS),
    "push_notification": _fields(SUBJECT, SENDER_NAME, BODY_TEXT, RICH_BODY_FIELDS),
    "branded": _fields(BRAND_NAME, SUBJECT, SENDER_NAME, BODY_TEXT, RICH_BODY_FIELDS),
}


def admin_missive_type_fields(missive_type: str | None) -> list[str]:
    """Return fields shown by the step admin for one exact missive type."""
    return list(ADMIN_MISSIVE_TYPE_FIELDS.get((missive_type or "").lower(), ()))


def admin_missive_type_exclusions(missive_type: str | None) -> list[str]:
    """Return inherited fields intentionally hidden for one missive type."""
    support = missive_support_for_type(missive_type or "")
    shown = set(admin_missive_type_fields(missive_type))
    return [name for name in CAMPAIGN_SOURCED_FIELDS.get(support, ()) if name not in shown]


def campaign_sourced_fields(support: str | None) -> list[str]:
    """Return a fresh list of fields a missive inherits for ``support``."""
    return list(CAMPAIGN_SOURCED_FIELDS.get((support or "").lower(), ()))


for _missive_type, _admin_fields in ADMIN_MISSIVE_TYPE_FIELDS.items():
    _support = missive_support_for_type(_missive_type)
    if not set(_admin_fields) <= set(CAMPAIGN_SOURCED_FIELDS.get(_support, ())):
        raise ValueError(f"Admin fields do not match inherited fields for {_missive_type!r}.")

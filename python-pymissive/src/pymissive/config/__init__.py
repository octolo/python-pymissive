"""Canonical key/value maps for missive types, events, fields and supports.

Keys are the values stored by consumers (Django ``CharField``, webhooks,
provider payloads). Labels and descriptions are display-only. django-pymissive
builds ``TextChoices`` from these maps at import: adding or renaming a key is
supposed to produce an ``AlterField``. That is not a schema change — the
column stays a string holding the key.
"""

from . import address
from . import email
from . import phone
from . import missive
from . import recipient
from . import attachment
from . import billing
from . import webhook


MISSIVE_TYPES = {
    **address.TYPES,
    **email.TYPES,
    **phone.TYPES,
}


SUCCESSFUL_EVENTS = {
    "delivered": ("Delivered", "successfully delivered to the recipient's mailbox."),
    "opened": ("Opened", "Recipient opened the missive (tracked via open pixel)."),
    "read": ("Read", "Recipient read the missive (may include extended tracking)."),
    "clicked": ("Clicked", "Recipient clicked a link in the missive."),
    "proofs_of_delivery": ("Proofs of Delivery", "Official confirmation of delivery for legal/transactional missives."),
}


FAILED_EVENTS = {
    "failed": ("Failed", "General failure to deliver."),
    "cancelled": ("Cancelled", "Sending was cancelled before delivery."),
    "hard_bounce": ("Hard bounce", "Permanent failure: cannot be delivered (e.g., address does not exist)."),
    "soft_bounce": ("Soft bounce", "Temporary failure: mailbox full, server busy, or other transient issues."),
    "dropped": ("Dropped", "Intentionally dropped by the system, often due to suppression rules."),
    "spam": ("Spam", "Identified as spam by the recipient or provider filters."),
    "spam_report": ("Spam report", "Recipient explicitly marked as spam."),
    "blocked": ("Blocked", "Delivery blocked by the provider due to policies or security rules."),
    "rejected": ("Rejected", "Rejected by the recipient's server (generic rejection)."),
    "refused": ("Refused", "Connection refused by the server at SMTP level."),
    "invalid": ("Invalid", "Address format is invalid or malformed."),
    "carrier_rejected": ("Carrier rejected", "Recipient's carrier/provider rejected due to reputation or policy."),
    "undelivered": ("Undelivered", "Could not be delivered for unspecified reasons."),
    "unsubscribe": ("Unsubscribe", "Recipient unsubscribed from further missives."),
    "suppressed": ("Suppressed", "Suppressed by the system due to prior bounces or preferences."),
    "mailbox_full": ("Mailbox full", "Recipient's mailbox is full, causing a temporary delivery failure."),
    "domain_not_found": ("Domain not found", "Recipient's domain does not exist or cannot be resolved."),
    "error": ("Error", "Error occurred while processing"),
}


INFO_EVENTS = {
    "untreated": ("Untreated", "Has not been processed yet."),
    "draft": ("Draft", "Saved as draft, not yet sent."),
    "sent": ("Sent", "Successfully sent from the sender server."),
    "accepted": ("Accepted", "Accepted by the provider for processing."),
    "processed": ("Processed", "Processed by the provider."),
    "deposit_proof": ("Deposit proof", "Deposit proof received from carrier."),
    "proof_of_content": ("Proof of content", "Proof of content received."),
    "archived": ("Archived", "Archived by the provider."),
    "attempted_delivery": ("Attempted delivery", "Delivery was attempted."),
    "prepare": ("Prepare", "Being prepared for sending."),
    "pending": ("Pending", "Waiting to be processed for sending."),
    "processing": ("Processing", "Currently being processed by the system."),
    "queued": ("Queued", "Queued and waiting for delivery."),
    "proxy": (
        "Proxy",
        "Intermediary progress (privacy proxy, in transit, or similar). Not a confirmed human action or final delivery.",
    ),
    "submitted": ("Submitted", "The missive was submitted for sending."),
    "request": ("Request", "A request to send the missive has been received."),
    "deferred": ("Deferred", "Temporary delivery failure, will retry later."),
    "scheduled": ("Scheduled", "Scheduled to be sent at a future time."),
    "unknown": ("Unknown", "Unknown event."),
}


ALL_EVENTS = {
    **SUCCESSFUL_EVENTS,
    **FAILED_EVENTS,
    **INFO_EVENTS,
}


MISSIVE_FIELDS = {
    **address.FIELDS,
    **email.FIELDS,
    **phone.FIELDS,
    **missive.FIELDS,
    **billing.FIELDS,
}

WEBHOOK_FIELDS = webhook.FIELDS


EMAIL_FIELDS = {
    **email.FIELDS,
    **missive.FIELDS,
}


PHONE_FIELDS = {
    **phone.FIELDS,
    **missive.FIELDS,
}


ADDRESS_FIELDS = {
    **address.FIELDS,
    **missive.FIELDS,
}


GENERIC_SUPPORT = {
    "email": ["email", "email_marketing", "ere"],
    "phone": ["sms", "rcs", "voice_call",],
    "address": ["letter", "registered_letter", "hand_delivery"],
    "application": ["notification", "push_notification", "branded"],
}


#: Events that prove the missive left the system. The oldest one dates the send
#: (see the ``sent_at`` annotation in django-pymissive): a delivered missive was
#: necessarily sent, even when the provider never emitted ``sent`` itself.
SENT_EVENTS = ("sent", "accepted", "delivered")


def normalize_missive_type(value: str) -> str:
    """Return the canonical missive-type key, or ``""`` when unknown.

    Only keys in ``MISSIVE_TYPES`` match (hyphens are treated as underscores).
    """
    key = str(value or "").strip().lower().replace("-", "_")
    if key in MISSIVE_TYPES:
        return key
    return ""


def missive_service_type(missive_type: str) -> str:
    """Type key used in provider service names (``send_letter``, ``send_registered_letter``, …).

    Unknown values raise: a pass-through used to build names like ``send_lre``
    that ``hasattr`` then treated as a quiet no-op.
    """
    key = normalize_missive_type(missive_type)
    if not key:
        raise ValueError(f"Unknown missive type: {missive_type!r}")
    return key


def provider_service_name(service: str, missive_type: str) -> str:
    """``{service}_{type}`` after :func:`missive_service_type`."""
    return f"{service}_{missive_service_type(missive_type)}"


def missive_support_for_type(missive_type: str) -> str:
    """Return the ``GENERIC_SUPPORT`` key owning ``missive_type``, or ``""``."""
    mt = normalize_missive_type(missive_type) or str(missive_type or "").strip().lower()
    if not mt:
        return ""
    for support, types in GENERIC_SUPPORT.items():
        if mt in types:
            return support
    return ""


def normalize_support(value: str) -> str:
    """Return the canonical support key for a support name or missive type.

    Accepts a support key (``address``, ``email``, ``phone``, ``application``)
    or a missive type from ``MISSIVE_TYPES`` (``letter``, ``registered_letter``,
    ``sms``, …). Hyphens are treated as underscores. Historical aliases
    (``postal``, ``courrier``, ``mail``, ``app``) are not accepted.
    Returns ``""`` when nothing matches.
    """
    key = str(value or "").strip().lower().replace("-", "_")
    if not key:
        return ""
    if key in GENERIC_SUPPORT:
        return key
    return missive_support_for_type(key)


def missive_types_for_support(support: str) -> list[str]:
    """Missive types belonging to ``support`` (inverse of :func:`missive_support_for_type`).

    ``support`` goes through :func:`normalize_support`. Returns ``[]`` for an
    unknown support.
    """
    return list(GENERIC_SUPPORT.get(normalize_support(support), []))

PRIORITIES = ["low", "normal", "high", "urgent"]
DELIVERY_MODES = ["economic", "normal", "premium", "express"]

MISSIVE_ACKNOWLEDGEMENT_LEVELS = [
    {
        "level": 0,
        "name": "basic_delivery",
        "display_name": "Basic delivery",
        "description": "Message sent / delivered. No proof of reading or identity.",
        "identity_verification": False,
        "signature": False,
        "legal_value": "Technical only",
        "means": [],
    },
    {
        "level": 1,
        "name": "acknowledgement_of_receipt",
        "display_name": "Acknowledgement of receipt",
        "description": "Recipient confirms receipt. No strong identity verification.",
        "identity_verification": False,
        "signature": False,
        "legal_value": None,
        "means": ["Reply email", "Acknowledge button"],
    },
    {
        "level": 2,
        "name": "authenticated_acknowledgement",
        "display_name": "Authenticated acknowledgement",
        "description": "Receipt confirmed. Authenticated identity (login, OTP, SSO).",
        "identity_verification": True,
        "signature": False,
        "legal_value": None,
        "means": ["User account", "MFA / OTP", "Secure portal"],
    },
    {
        "level": 3,
        "name": "signed_acknowledgement",
        "display_name": "Signed acknowledgement",
        "description": "Receipt confirmed. Electronic signature. Full traceability.",
        "identity_verification": True,
        "signature": True,
        "legal_value": None,
        "means": ["Simple or advanced e-signature"],
    },
    {
        "level": 4,
        "name": "qualified_acknowledgement",
        "display_name": "Qualified / legally binding acknowledgement",
        "description": "Receipt + high-level verified identity + Qualified signature.",
        "identity_verification": True,
        "signature": True,
        "legal_value": "Strong legal value (eIDAS)",
        "means": ["eIDAS qualified signature", "eDelivery / eRegistered mail"],
    },
]


MISSIVE_SERVICES = {
    "missive": {
        "services": missive.SERVICES,
        "config": MISSIVE_FIELDS,
    },
    "recipient": {
        "services": recipient.SERVICES,
        "config": recipient.FIELDS,
    },
    "attachment": {
        "services": attachment.SERVICES,
        "config": attachment.FIELDS,
    },
    "billing": {
        "services": billing.SERVICES,
        "config": billing.FIELDS,
    },
    "webhook": {
        "services": webhook.SERVICES,
        "config": webhook.FIELDS,
    },
}


_SUPPORT_FIELDS = {
    "email": EMAIL_FIELDS,
    "phone": PHONE_FIELDS,
    "address": ADDRESS_FIELDS,
}


def get_config_by_support(missive_type: str) -> dict:
    """Return fields dict for the support category that contains missive_type."""
    support_key = missive_support_for_type(missive_type)
    if support_key:
        return _SUPPORT_FIELDS.get(support_key, MISSIVE_FIELDS)
    return MISSIVE_FIELDS


def fields_to_arg_config(fields: dict, default_str: str = "") -> dict:
    """Build clicommands _ARG_CONFIG from config FIELDS. Maps format to argparse type."""
    _FORMAT_TO_TYPE = {
        "str": (str, default_str),
        "int": (int, 0),
        "float": (float, 0.0),
        "bool": ("store_true", False),
        "list": (str, default_str),
        "datetime": (str, default_str),
        "file": (str, default_str),
    }
    result = {}
    for name, field in fields.items():
        fmt = field.get("format")
        if isinstance(fmt, list):
            fmt = fmt[0] if fmt else "str"
        type_spec, default = _FORMAT_TO_TYPE.get(fmt, (str, default_str))
        if type_spec == "store_true":
            result[name] = {"type": "store_true", "default": default}
        else:
            result[name] = {"type": type_spec, "default": default}
    return result


def get_missive_send_arg_config() -> dict:
    """Arg config for missive send from config FIELDS. Includes recipient shortcuts from recipient.RECIPIENT_FIELDS."""
    send_fields = {
        k: v
        for k, v in {**email.FIELDS, **phone.FIELDS, **address.FIELDS, **missive.FIELDS}.items()
        if k in ("subject", "body_rich", "body_text", "body", "recipients", "sender_name", "sender_email", "sender_phone", "sender_address", "reply_to_name", "reply_to_email")
    }
    for k in ("name", "email", "phone", "address"):
        if k in recipient.RECIPIENT_FIELDS:
            send_fields[f"recipient_{k}"] = recipient.RECIPIENT_FIELDS[k]
    send_fields.setdefault("body_text", {"format": "str"})
    send_fields.setdefault("body", {"format": "str"})
    return fields_to_arg_config(send_fields)
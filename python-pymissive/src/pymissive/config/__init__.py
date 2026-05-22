"""Config for pymissive."""

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
    "address": ["lre", "hand_delivery"],
    "application": ["push_notification", "branded"],
}

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


def get_config_by_support(missive_type: str) -> dict:
    """Return fields dict for the support category that contains missive_type."""
    support_key = next((k for k, types in GENERIC_SUPPORT.items() if missive_type in types), None)
    if support_key:
        return getattr(globals(), f"{support_key.upper()}_FIELDS", MISSIVE_FIELDS)
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
        if k in ("subject", "body_html", "body_text", "body", "recipients", "sender_name", "sender_email", "sender_phone", "sender_address", "reply_to_name", "reply_to_email")
    }
    for k in ("name", "email", "phone", "address"):
        if k in recipient.RECIPIENT_FIELDS:
            send_fields[f"recipient_{k}"] = recipient.RECIPIENT_FIELDS[k]
    send_fields.setdefault("body_text", {"format": "str"})
    send_fields.setdefault("body", {"format": "str"})
    return fields_to_arg_config(send_fields)
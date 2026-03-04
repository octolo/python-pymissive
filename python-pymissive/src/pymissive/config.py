"""Missive configuration."""


MISSIVE_TYPES = {
    "postal": "Postal mail",
    "postal_registered": "Registered postal mail",
    "postal_signature": "Registered postal mail with signature",
    "lre": "Electronic registered letter",
    "lre_qualified": "Qualified electronic registered letter",
    "ere": "Electronic registered email (ERE)",
    "email": "Email",
    "email_marketing": "Marketing email",
    "sms": "SMS",
    "rcs": "RCS (Rich SMS)",
    "voice_call": "Automated voice call",
    "notification": "In-app notification",
    "push_notification": "Mobile push notification",
    "branded": "Branded App messaging (WhatsApp, Slack, etc.)",
}

MISSIVE_SERVICES = {
    # SEND
    "prepare": "Prepare",
    "update": "Update",
    "cancel": "Cancel",
    "send": "Send",
    "delete": "Delete",
    "status": "Status",
    # ATTACHMENTS
    "add_attachment": "Add Attachment",
    "get_attachments": "Get Attachments",
    "delete_attachment": "Delete Attachment",
    # WEBHOOKS
    "set_webhook": "set_Webhook",
    "update_webhook": "Update Webhook",
    "handle_webhook": "Handle Webhook",
    "delete_webhook": "Delete Webhook",
    "get_webhooks": "Get Webhooks",
    # HELPERS
    "monitoring": "Monitoring",
    "billing_amount": "Billing Amount",
    "estimate_amount": "Estimate Amount",
    "get_proofs": "Get Proofs",
    "download_proof": "Download Proof",
}

MISSIVE_EVENT_SUCCESS = {
    "delivered": "Delivered",
    "read": "Read",
    "opened": "Opened",
    "click": "Clicked",
    "clicked": "Clicked",
    "proofs_of_delivery": "Proofs of Delivery",
}

MISSIVE_EVENT_INFO = {
    "draft": "Draft",
    "sent": "Sent",
    "prepare": "Prepare",
    "pending": "Pending",
    "processing": "Processing",
    "queued": "Queued",
    "request": "Request",
    "deferred": "Deferred",
    "scheduled": "Scheduled",
    "unknown_type": "Unknown type",
    "attempted_delivery": "Attempted delivery",
    "mailed": "Mailed",
    "printed": "Printed",
    "accepted": "Accepted",
    "dispatched": "Dispatched",
    "shipped": "Shipped",
    "in_transit": "In transit",
    "deposit_proof": "Deposit Proof",
    "proof_of_content": "Proof of Content",
    "archived": "Archived",
}

MISSIVE_EVENT_FAILED = {
    "failed": "Failed",
    "cancelled": "Cancelled",
    "bounced": "Bounced",
    "hard_bounce": "Hard bounce",
    "soft_bounce": "Soft bounce",
    "hardBounce": "Hard bounce",
    "softBounce": "Soft bounce",
    "dropped": "Dropped",
    "spam": "Spam",
    "blocked": "Blocked",
    "invalid": "Invalid",
    "mailbox_not_found": "Mailbox not found",
    "blocklisted": "Blocklisted",
    "blocklist_created": "Blocklist created",
    "rejected": "Rejected",
    "undelivered": "Undelivered",
    "undeliverable": "Undeliverable",
    "expired": "Expired",
    "carrier_rejected": "Carrier rejected",
    "return_to_sender": "Return to sender",
    "refused": "Refused",
    "lost": "Lost",
    "damaged": "Damaged",
    "out_for_delivery": "Out for delivery",
    "error": "Error",
}

MISSIVE_EVENT = {**MISSIVE_EVENT_SUCCESS, **MISSIVE_EVENT_INFO, **MISSIVE_EVENT_FAILED}

MISSIVE_WEBHOOK_FIELDS = {
    "webhook_id": {
        "label": "Webhook ID",
        "description": "Webhook ID",
        "format": "str",
    },
    "id": {
        "label": "ID",
        "description": "ID",
        "format": "str",
    },
    "type": {
        "label": "Type",
        "description": "Type",
        "format": "str",
    },
    "url": {
        "label": "URL",
        "description": "URL",
        "format": "str",
    },
    "description": {
        "label": "Description",
        "description": "Description",
        "format": "str",
    },
    "created_at": {
        "label": "Created At",
        "description": "Created At",
        "format": "datetime",
    },
    "updated_at": {
        "label": "Updated At",
        "description": "Updated At",
        "format": "datetime",
    },

}

MISSIVE_FIELDS_BASE = {
    "webhook_url": {
        "label": "Webhook URL",
        "description": "Webhook URL",
        "format": "str",
    },
    "external_id": {
        "label": "External ID",
        "description": "External ID",
        "format": "str",
    },
    "recipient": {
        "label": "Recipient",
        "description": "Recipient",
        "format": "str",
    },
    "recipients_external_ids": {
        "label": "Recipients External IDs",
        "description": "Recipients External IDs",
        "format": "dict",
    },
    "status": {
        "label": "Status",
        "description": "Status",
        "format": "str",
    },
    "event": {
        "label": "Event",
        "description": "Event",
        "format": "str",
    },
    "description": {
        "label": "Description",
        "description": "Description",
        "format": "str",
    },
    "occurred_at": {
        "label": "Occurred At",
        "description": "Occurred At",
        "format": "datetime",
    },
    "currency": {
        "label": "Currency",
        "description": "Currency",
        "format": "str",
    },
    "error_message": {
        "label": "Error Message",
        "description": "Error Message",
        "format": "str",
    },
    "billing_amount": {
        "label": "Billing Amount",
        "description": "Billing Amount",
        "format": "float",
    },
    "estimate_amount": {
        "label": "Estimate Amount",
        "description": "Estimate Amount",
        "format": "float",
    },
    "is_billed": {
        "label": "Is Billed",
        "description": "Is Billed",
        "format": "bool",
    },
}

MISSIVE_FIELDS_EMAIL = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "email": {
        "label": "Email",
        "description": "Email",
        "format": "str",
    },
    "subject": {
        "label": "Subject",
        "description": "Subject",
        "format": "str",
    },
    "body": {
        "label": "Body",
        "description": "Body",
        "format": "str",
    },
    "body_text": {
        "label": "Body Text",
        "description": "Body Text",
        "format": "str",
    },
    "attachments": {
        "label": "Attachments",
        "description": "Attachments",
        "format": "list",
    },
    "reply_to": {
        "label": "Reply To",
        "description": "Reply To",
        "format": "str",
    },
    "cc": {
        "label": "CC",
        "description": "Carbon Copy",
        "format": "list",
    },
    "bcc": {
        "label": "BCC",
        "description": "Blind Carbon Copy",
        "format": "list",
    },
    "sender_name": {
        "label": "Sender Name",
        "description": "Sender Name",
        "format": "str",
    },
    "sender_email": {
        "label": "Sender Email",
        "description": "Sender Email",
        "format": "str",
    },
    **MISSIVE_FIELDS_BASE,
}

MISSIVE_FIELDS_PHONE = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "phone": {
        "label": "Recipient Phone",
        "description": "Recipient Phone",
        "format": "str",
    },
    "sender_name": {
        "label": "Sender Name",
        "description": "Sender Name",
        "format": "str",
    },
    "sender_phone": {
        "label": "Sender Phone",
        "description": "Sender Phone",
        "format": "str",
    },
    **MISSIVE_FIELDS_BASE,
}

MISSIVE_FIELDS_POSTAL = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "address": {
        "label": "Address",
        "description": "Address",
        "format": "str",
    },
    "color": {
        "label": "Color",
        "description": "Color",
        "format": "bool",
    },
    "duplex": {
        "label": "Duplex",
        "description": "Duplex",
        "format": "bool",
    },
    **MISSIVE_FIELDS_BASE,
}

MISSIVE_FIELDS_NOTIFICATION = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "notification_id": {
        "label": "Notification ID",
        "description": "Notification ID",
        "format": "str",
    },
    **MISSIVE_FIELDS_BASE,
}

MISSIVE_FIELDS_PUSH_NOTIFICATION = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "push_notification_id": {
        "label": "Push Notification ID",
        "description": "Push Notification ID",
        "format": "str",
    },
    **MISSIVE_FIELDS_BASE,
}

MISSIVE_FIELDS_BRANDED = {
    "name": {
        "label": "Name",
        "description": "Name",
        "format": "str",
    },
    "brand": {
        "label": "Brand",
        "description": "Brand",
        "format": "str",
    },
    "target": {
        "label": "Target",
        "description": "Target",
        "format": "str",
    },
    **MISSIVE_FIELDS_BASE,
}

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

MISSIVE_GENERIC_SUPPORT = {
    "EMAIL": ["email", "email_marketing"],
    "PHONE": ["sms", "rcs", "voice_call"],
    "POSTAL": ["postal", "postal_registered", "postal_signature", "lre", "lre_qualified", "ere"],
    "NOTIFICATION": ["notification", "push_notification"],
    "BRANDED": ["branded"],
}

type_to_fields_mapping = {
    "email": "MISSIVE_FIELDS_EMAIL",
    "email_marketing": "MISSIVE_FIELDS_EMAIL",
    "sms": "MISSIVE_FIELDS_PHONE",
    "rcs": "MISSIVE_FIELDS_PHONE",
    "voice_call": "MISSIVE_FIELDS_PHONE",
    "postal": "MISSIVE_FIELDS_POSTAL",
    "postal_registered": "MISSIVE_FIELDS_POSTAL",
    "postal_signature": "MISSIVE_FIELDS_POSTAL",
    "lre": "MISSIVE_FIELDS_POSTAL",
    "lre_qualified": "MISSIVE_FIELDS_POSTAL",
    "ere": "MISSIVE_FIELDS_POSTAL",
    "notification": "MISSIVE_FIELDS_NOTIFICATION",
    "push_notification": "MISSIVE_FIELDS_PUSH_NOTIFICATION",
    "branded": "MISSIVE_FIELDS_BRANDED",
}

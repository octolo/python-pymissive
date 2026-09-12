SERVICES = {
    "add_recipient": "Add Recipient",
    "update_recipient": "Update Recipient",
    "delete_recipient": "Delete Recipient",
    "tracking_number": "Retrieve carrier tracking numbers",
}

SENDER_FIELDS = {
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
    "sender_phone": {
        "label": "Sender Phone",
        "description": "Sender Phone",
        "format": "str",
    },
    "sender_address": {
        "label": "Sender Address",
        "description": "Sender Address",
        "format": "str",
    },
}

REPLY_TO_FIELDS = {
    "reply_to_name": {
        "label": "Reply To Name",
        "description": "Reply To Name",
        "format": "str",
    },
    "reply_to_email": {
        "label": "Reply To Email",
        "description": "Reply To Email",
        "format": "str",
    },
    "reply_to_phone": {
        "label": "Reply To Phone",
        "description": "Reply To Phone",
        "format": "str",
    },
    "reply_to_address": {
        "label": "Reply To Address",
        "description": "Reply To Address",
        "format": "str",
    },
}

RECIPIENT_FIELDS = {
    "recipient_type": {
        "label": "Recipient Type",
        "description": "Recipient Type (recipient, cc, bcc, etc.)",
        "format": "str",
    },
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
    "phone": {
        "label": "Phone",
        "description": "Phone",
        "format": "str",
    },
    "address": {
        "label": "Address",
        "description": "Address",
        "format": "str",
    },
    "notification_id": {
        "label": "Notification ID",
        "description": "Notification ID",
        "format": "str",
    },
    "external_id": {
        "label": "External ID",
        "description": "External ID",
        "format": "str",
    },
    "tracking_number": {
        "label": "Tracking number",
        "description": "Carrier tracking reference for public tracking sites (e.g. La Poste)",
        "format": "str",
    },
    "internal_id": {
        "label": "Internal ID",
        "description": "Internal ID",
        "format": "str",
    },
    "substitute_id": {
        "label": "Substitute ID",
        "description": "Provider custom_id from another internal reference. When empty, the local id is used.",
        "format": "str",
    },
    "sent_at": {
        "label": "Sent At",
        "description": "Sent At",
        "format": "datetime",
    },
    "delivered_at": {
        "label": "Delivered At",
        "description": "Delivered At",
        "format": "datetime",
    },
}

FIELDS = {
    **SENDER_FIELDS,
    **REPLY_TO_FIELDS,
    **RECIPIENT_FIELDS,
}
SERVICES = {
    "create": "Create",
    "retrieve": "Retrieve",
    "update": "Update",
    "delete": "Delete",
    "cancel": "Cancel",
    "send": "Send",
    "preview": "Preview",
}

FIELDS = {
    "external_id": {
        "label": "External ID",
        "description": "External ID",
        "format": "str",
    },
    "internal_id": {
        "label": "Internal ID",
        "description": "Internal ID",
        "format": "str",
    },
    "recipients": {
        "label": "Recipients",
        "description": "Recipients",
        "format": "list",
    },
    "attachments": {
        "label": "Attachments",
        "description": "Attachments",
        "format": "list",
    },
    "events": {
        "label": "Events",
        "description": "Normalized events for handle_events()",
        "format": "list",
    },
}
SERVICES = {
    "create": "Create",
    "retrieve": "Retrieve missive information from partner ID or internal ID",
    "retrieve_events": "Retrieve events in bulk",
    "update": "Update",
    "delete": "Delete",
    "cancel": "Cancel",
    "send": "Send",
    "preview": "Preview",
}

FIELDS = {
    "external_id": {
        "label": "External ID",
        "description": "External ID (partner / provider identifier)",
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
    "start_date": {
        "label": "Start date",
        "description": "Start date for bulk event retrieval",
        "format": "datetime",
    },
    "end_date": {
        "label": "End date",
        "description": "End date for bulk event retrieval",
        "format": "datetime",
    },
}
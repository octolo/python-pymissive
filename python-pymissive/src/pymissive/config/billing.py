SERVICES = {
    "get_billings": "Get Billings",
    "retrieve_billings": "Retrieve billings in bulk",
}

FIELDS = {
    "start_date": {
        "label": "Start date",
        "description": "Start date for bulk billing retrieval",
        "format": "datetime",
    },
    "end_date": {
        "label": "End date",
        "description": "End date for bulk billing retrieval",
        "format": "datetime",
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
    "is_billed_by_provider": {
        "label": "Is Billed by Provider",
        "description": "Is Billed by Provider",
        "format": "bool",
    },
    "currency": {
        "label": "Currency",
        "description": "ISO 4217 currency code (e.g. EUR, USD)",
        "format": "str",
    },
    "invoice": {
        "label": "Detail",
        "description": "Detail",
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
        "format": "dict",
    },
    "substitute_id": {
        "label": "Substitute ID",
        "description": "Provider custom_id / user_reference used to match a missive",
        "format": "str",
    },
}
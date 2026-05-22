TYPES = {
    "lre": "Electronic registered letter (LRE)",
    "hand_delivery": "Hand delivery",
}

FIELDS = {
    "sender_name": {
        "label": "Sender Name",
        "description": "Sender Name",
        "format": "str",
    },
    "sender_address": {
        "label": "Sender Address",
        "description": "Sender Address",
        "format": "str",
    },
    "reply_to_name": {
        "label": "Reply To Name",
        "description": "Reply To Name",
        "format": "str",
    },
    "reply_to_address": {
        "label": "Reply To Address",
        "description": "Reply To Address",
        "format": "str",
    },
    "acknowledgement_of_receipt": {
        "label": "Acknowledgement of Receipt",
        "description": "Acknowledgement of Receipt",
        "format": "bool",
    },
    "color_printing": {
        "label": "Color Printing",
        "description": "Color Printing",
        "format": "bool",
    },
    "duplex_printing": {
        "label": "Duplex Printing",
        "description": "Duplex Printing",
        "format": "bool",
    },
    "envelope_windows_type": {
        "label": "Envelope Windows Type",
        "description": "Envelope Windows Type",
        "format": "str",
    },
    "archiving_duration": {
        "label": "Archiving Duration",
        "description": "Archiving Duration",
        "format": "int",
    },
    "optional_address_sheet": {
        "label": "Optional Address Sheet",
        "description": "Optional Address Sheet",
        "format": "bool",
    },
    "print_sender_address": {
        "label": "Print Sender Address",
        "description": "Print Sender Address",
        "format": "bool",
    },
    "return_envelope": {
        "label": "Return Envelope",
        "description": "Return Envelope",
        "format": "bool",
    },
    "postage_type": {
        "label": "Postage Type",
        "description": "Postage Type",
        "format": "str",
    },
    "subject": {
        "label": "Subject",
        "description": "Subject",
        "format": "str",
    },
    "first_document": {
        "label": "First Document",
        "description": "First document (HTML body converted to PDF for LRE)",
        "format": ["str", "file"],
    },
}
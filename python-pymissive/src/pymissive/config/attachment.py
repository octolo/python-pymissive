SERVICES = {
    "retrieve_attachments": "Retrieve Attachments",
    "add_attachment": "Add Attachment",
    "update_attachment": "Update Attachment",
    "delete_attachment": "Delete Attachment",
    "retrieve_proofs": "Retrieve Proofs",
    "download_proof": "Download Proof",
}

FIELDS = {
    "attachment_file": {
        "label": "Attachment File",
        "description": "Attachment File",
        "format": "file",
    },
    "external_id": {
        "label": "External ID",
        "description": "External ID",
        "format": "str",
    },
    "page_count": {
        "label": "Page Count",
        "description": "Page Count",
        "format": "int",
    },
    "linked": {
        "label": "Linked",
        "description": "If true, the attachment is offered as an access link instead of being physically attached",
        "format": "bool",
    },
    "priority": {
        "label": "Priority",
        "description": "Priority",
        "format": "int",
    },
    "attachment_type": {
        "label": "Attachment Type",
        "description": "Attachment Type (attachment, signature, receipt, proof, other)",
        "format": "str",
    },
    "filename": {
        "label": "Filename",
        "description": "Filename",
        "format": "str",
    },
    "url": {
        "label": "URL",
        "description": "URL",
        "format": "str",
    },
}
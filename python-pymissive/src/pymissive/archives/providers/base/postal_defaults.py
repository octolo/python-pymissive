"""Shared constants for postal providers."""

POSTAL_DEFAULT_MIME_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/rtf",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]

POSTAL_ENVELOPE_LIMITS = [
    {
        "format": "C4 double-window",
        "dimensions_mm": "210x300",
        "max_sheets": 45,
    },
    {
        "format": "DL simple/double-window",
        "dimensions_mm": "114x229",
        "max_sheets": 5,
    },
]

__all__ = ["POSTAL_DEFAULT_MIME_TYPES", "POSTAL_ENVELOPE_LIMITS"]

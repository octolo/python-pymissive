"""Framework-agnostic helpers for pymissive."""

from __future__ import annotations

import os

#: Default ``urlopen`` / ``requests`` timeout (seconds). ``None`` would wait forever.
HTTP_TIMEOUT = 30
#: Uploads and downloads of PDFs (Maileva LRE, deposit proofs).
HTTP_DOCUMENT_TIMEOUT = 120


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped.

    Reads ``PYMISSIVE_DISABLE_SEND`` from the environment first, then from
    Django settings when available. Defaults to False.
    """
    env = os.environ.get("PYMISSIVE_DISABLE_SEND")
    if env is not None:
        return _truthy(env)
    try:
        from django.conf import settings

        return _truthy(getattr(settings, "PYMISSIVE_DISABLE_SEND", False))
    except Exception:
        return False

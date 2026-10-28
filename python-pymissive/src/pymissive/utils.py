"""Framework-agnostic helpers for pymissive."""

from __future__ import annotations

import os
from urllib.parse import urlparse

#: Default ``urlopen`` / ``requests`` timeout (seconds). ``None`` would wait forever.
HTTP_TIMEOUT = 30
#: Uploads and downloads of PDFs (Maileva registered letter, deposit proofs).
HTTP_DOCUMENT_TIMEOUT = 120


def require_https_url(url: str) -> str:
    """Reject URLs that could make HTTP clients open local or credentialed resources."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must be an HTTPS URL without embedded credentials")
    return url


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def _flag(name: str) -> bool:
    """Read a boolean from the environment first, then from Django settings."""
    env = os.environ.get(name)
    if env is not None:
        return _truthy(env)
    try:
        from django.conf import settings

        return _truthy(getattr(settings, name, False))
    except Exception:
        return False


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped (``PYMISSIVE_DISABLE_SEND``)."""
    return _flag("PYMISSIVE_DISABLE_SEND")


def is_fake_provider_allowed() -> bool:
    """Return True when the ``fake`` provider may accept sends (``PYMISSIVE_ALLOW_FAKE_PROVIDER``)."""
    return _flag("PYMISSIVE_ALLOW_FAKE_PROVIDER")


def is_force_fake_provider() -> bool:
    """Return True when every missive must use the local ``fake`` provider.

    ``PYMISSIVE_FORCE_FAKE_PROVIDER``. The fake provider then accepts the
    send even if ``PYMISSIVE_ALLOW_FAKE_PROVIDER`` is off.
    """
    return _flag("PYMISSIVE_FORCE_FAKE_PROVIDER")

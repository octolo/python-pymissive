"""Framework-agnostic helpers for pymissive."""

from __future__ import annotations

import os
from urllib.parse import urlparse

#: Default ``urlopen`` / ``requests`` timeout (seconds). ``None`` would wait forever.
HTTP_TIMEOUT = 30
#: Uploads and downloads of large documents and proofs.
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


def setting_value(name: str, default=None):
    """Read an environment variable, then the matching Django setting."""
    env = os.environ.get(name)
    if env is not None:
        return env
    try:
        from django.conf import settings

        return getattr(settings, name, default)
    except Exception:
        return default


def setting_flag(name: str) -> bool:
    """Read a boolean setting or environment variable."""
    return _truthy(setting_value(name, False))


def is_disable_send() -> bool:
    """Return True when provider ``send`` calls must be skipped (``PYMISSIVE_DISABLE_SEND``)."""
    return setting_flag("PYMISSIVE_DISABLE_SEND")


def forced_provider_name() -> str:
    """Provider override from ``PYMISSIVE_FORCE_PROVIDER``, empty when disabled."""
    return str(setting_value("PYMISSIVE_FORCE_PROVIDER", "") or "").strip()

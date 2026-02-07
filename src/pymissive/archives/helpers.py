"""Framework-agnostic helpers - Imports from geoaddress for address functions."""

from __future__ import annotations

import os

# Address helpers - Import from geoaddress
try:
    from geoaddress.helpers import (
        DEFAULT_MIN_ADDRESS_CONFIDENCE,
        describe_address_backends,
        get_address_backend_by_attribute,
        get_address_backends_from_config,
        get_address_by_reference,
        search_addresses,
    )
except ImportError:
    DEFAULT_MIN_ADDRESS_CONFIDENCE = 0.4
    describe_address_backends = None
    get_address_backend_by_attribute = None
    get_address_backends_from_config = None
    get_address_by_reference = None
    search_addresses = None

# Phone helper - Stub (was in original helpers.py)
def format_phone_international(phone: str, country_code: str | None = None) -> str:
    """Format phone to international - Stub, needs restoration."""
    if not phone:
        return ""
    # Basic E.164 format attempt
    cleaned = ''.join(c for c in phone if c.isdigit())
    if phone.startswith('+'):
        return phone
    if country_code == "FR" and cleaned.startswith('0'):
        return f"+33{cleaned[1:]}"
    return f"+{cleaned}"

# Provider helpers - Stubs (need restoration from backup)
def get_providers_from_config(providers_config=None, on_error=None):
    """Stub - needs restoration."""
    return []

def get_provider_paths_from_config(providers_config=None):
    """Stub - needs restoration."""
    return {}

def get_provider_by_attribute(providers_config=None, attribute="", value="", on_error=None):
    """Stub - needs restoration."""
    return None

__all__ = [
    "DEFAULT_MIN_ADDRESS_CONFIDENCE",
    "describe_address_backends",
    "format_phone_international",
    "get_address_backend_by_attribute",
    "get_address_backends_from_config",
    "get_address_by_reference",
    "get_provider_by_attribute",
    "get_providers_from_config",
    "get_provider_paths_from_config",
    "search_addresses",
]

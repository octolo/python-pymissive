"""Framework-agnostic helpers for python-missive."""

from __future__ import annotations


# Phone helper
def format_phone_international(phone: str, country_code: str | None = None) -> str:
    """Format phone to international E.164 format.
    
    Args:
        phone: Phone number to format
        country_code: ISO country code (e.g., 'FR', 'US')
    
    Returns:
        Phone number in E.164 format (e.g., '+33612345678')
    """
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
    """Get providers from configuration - stub, needs restoration."""
    return []

def get_provider_paths_from_config(providers_config=None):
    """Get provider paths from configuration - stub, needs restoration."""
    return {}

def get_provider_by_attribute(providers_config=None, attribute="", value="", on_error=None):
    """Get provider by attribute - stub, needs restoration."""
    return None

__all__ = [
    "format_phone_international",
    "get_provider_by_attribute",
    "get_providers_from_config",
    "get_provider_paths_from_config",
]

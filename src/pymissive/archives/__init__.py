"""Lightweight multi-channel messaging helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Union

from .address import Address
from .address_backends import (BaseAddressBackend, GoogleMapsAddressBackend,
                               HereAddressBackend, MapboxAddressBackend,
                               NominatimAddressBackend, PhotonAddressBackend)
from .helpers import (
    DEFAULT_MIN_ADDRESS_CONFIDENCE,
    describe_address_backends,
    format_phone_international,
    get_address_backend_by_attribute,
    get_address_backends_from_config,
    get_address_by_reference,
    get_provider_by_attribute,
    search_addresses,
)
from .missive import Missive
from .providers.base.common import BaseProviderCommon
from .sender import MissiveSender
from .status import MissiveStatus

__all__ = [
    "MissiveStatus",
    "BaseProviderCommon",
    "Address",
    "Missive",
    "MissiveSender",
    "send_missive",
    "format_phone_international",
    "get_address_backends_from_config",
    "get_address_by_reference",
    "search_addresses",
    "get_address_backend_by_attribute",
    "describe_address_backends",
    "get_provider_by_attribute",
    "DEFAULT_MIN_ADDRESS_CONFIDENCE",
    "BaseAddressBackend",
    "GoogleMapsAddressBackend",
    "HereAddressBackend",
    "MapboxAddressBackend",
    "NominatimAddressBackend",
    "PhotonAddressBackend",
]


def send_missive(
    missive_type: str,
    body: str,
    subject: Optional[str] = None,
    recipient_email: Optional[str] = None,
    recipient_phone: Optional[str] = None,
    recipient: Optional[Any] = None,
    providers_config: Optional[Union[Sequence[str], Dict[str, Dict[str, Any]]]] = None,
    config: Optional[Dict[str, Any]] = None,
    sandbox: bool = False,
    enable_fallback: bool = True,
    **kwargs: Any,
) -> Missive:
    """Send a missive with automatic provider selection and fallback.

    Args:
        missive_type: Type of missive (EMAIL, SMS, POSTAL, etc.)
        body: Message body/content
        subject: Message subject (required for EMAIL)
        recipient_email: Recipient email address (for EMAIL)
        recipient_phone: Recipient phone number (for SMS, VOICE_CALL)
        recipient: Complex recipient object with metadata (for PUSH_NOTIFICATION, etc.)
        providers_config: Either:
            - List of provider import paths: ["pymissive.providers.brevo.BrevoProvider"]
            - Dict mapping paths to configs: {"path": {"API_KEY": "value"}}
        config: Default configuration dict merged with provider-specific configs
        sandbox: If True, forces sandbox mode for all providers (no real sends)
        enable_fallback: If True, try next provider on failure
        **kwargs: Additional options (provider_options, is_registered, etc.)

    Returns:
        Missive object with updated status

    Raises:
        RuntimeError: If all providers fail
        ValueError: If required fields are missing

    Example:
        >>> missive = send_missive(
        ...     "EMAIL",
        ...     body="Hello world",
        ...     subject="Test",
        ...     recipient_email="user@example.com",
        ... )
        >>> print(missive.status)
        MissiveStatus.SENT
    """
    missive_type = missive_type.upper()

    # Validate required fields based on type
    if missive_type == "EMAIL" and not recipient_email:
        raise ValueError("recipient_email required for EMAIL missives")
    if missive_type == "EMAIL" and not subject:
        raise ValueError("subject required for EMAIL missives")
    if missive_type in ("SMS", "VOICE_CALL") and not recipient_phone:
        raise ValueError(f"recipient_phone required for {missive_type} missives")
    if (
        missive_type in ("POSTAL", "POSTAL_REGISTERED")
        and not recipient
        and not recipient_email
    ):
        raise ValueError(
            f"recipient or recipient_email required for {missive_type} missives"
        )

    # Create missive object
    missive = Missive(
        missive_type=missive_type,
        body=body,
        subject=subject,
        recipient_email=recipient_email,
        recipient_phone=recipient_phone,
        recipient=recipient,
        provider_options=kwargs.get("provider_options", {}),
        is_registered=kwargs.get("is_registered", missive_type == "POSTAL_REGISTERED"),
        requires_signature=kwargs.get("requires_signature", False),
    )

    # Create sender and send
    sender = MissiveSender(
        providers_config=providers_config,
        default_config=config,
        sandbox=sandbox,
    )

    try:
        sender.send(missive, enable_fallback=enable_fallback)
    except Exception as e:
        missive.status = MissiveStatus.FAILED
        missive.error_message = str(e)
        raise

    return missive

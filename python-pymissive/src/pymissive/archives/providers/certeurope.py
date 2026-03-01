"""Certeurope provider for electronic registered letters (LRE)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..status import MissiveStatus
from .base import BaseProvider


class CerteuropeProvider(BaseProvider):
    """
    Certeurope provider (Electronic Registered Letter).

    Required configuration:
        CERTEUROPE_API_KEY: Certeurope API key
        CERTEUROPE_API_SECRET: API Secret
        CERTEUROPE_API_URL: API URL
        CERTEUROPE_SENDER_EMAIL: Registered sender email

    Recipient must have an email and complete postal address.
    """

    name = "certeurope"
    display_name = "Certeurope (LRE)"
    supported_types = ["LRE"]
    lre_price = 5.5
    lre_page_price_black_white = 0.0
    lre_page_price_color = 0.0
    lre_page_price_single_sided = 0.0
    lre_page_price_duplex = 0.0
    lre_allowed_attachment_mime_types: List[str] = ["application/pdf"]
    lre_allowed_page_formats: List[str] = []
    lre_envelope_limits: List[Dict[str, Any]] = []
    lre_page_limit = 200
    lre_color_printing_available = False
    lre_duplex_printing_available = False
    lre_archiving_duration = 3650
    config_keys = [
        "CERTEUROPE_API_KEY",
        "CERTEUROPE_API_SECRET",
        "CERTEUROPE_API_URL",
        "CERTEUROPE_SENDER_EMAIL",
    ]
    required_packages = ["requests"]
    site_url = "https://www.certeurope.fr/"
    description_text = "Electronic registered email with legal value (LRE)"
    # Geographic scope
    lre_geographic_coverage = ["Europe"]

    def validate(self) -> tuple[bool, str]:
        """Validate that the recipient has an email and address"""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient or not getattr(recipient, "email", None):
            return False, "Recipient must have an email for Certeurope ERL"

        # Check postal address (often required)
        warnings = []
        if not getattr(recipient, "address_line1", None):
            warnings.append("Postal address missing")
        if not getattr(recipient, "postal_code", None) or not getattr(
            recipient, "city", None
        ):
            warnings.append("Postal code and city required")
        if not getattr(recipient, "name", None):
            warnings.append("Recipient name required")

        if warnings:
            return False, "; ".join(warnings)

        return True, ""

    def send_lre(self, **kwargs) -> bool:
        """
        Send an LRE via Certeurope.

        TODO: Implement actual sending via Certeurope API
        """
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        # 1. Generate the letter PDF
        # 2. Create SOAP/REST Certeurope request
        # 3. Send the signed document
        # 4. Retrieve the deposit certificate

        missive_id = getattr(self.missive, "id", "unknown")
        external_id = f"certeurope_sim_{missive_id}"
        self._update_status(MissiveStatus.SENT, external_id=external_id)

        return True

    def get_lre_service_info(self) -> dict[str, Any]:
        """Return the service descriptor for LRE deliveries."""
        return {
            "provider": self.name,
            "services": ["lre"],
            "geographic_coverage": self.lre_geographic_coverage,
            "features": [
                "Qualified electronic registered letters",
                "Deposit and presentation certificates",
                "Acknowledgement of receipt",
                "Qualified timestamps",
                "10-year archiving",
            ],
        }

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """
        Check the LRE status (sending, reception, AR).

        TODO: Implement verification via Certeurope API
        """
        return None

    def get_proofs_of_delivery(self, service_type: Optional[str] = None) -> list:
        """
        Get all Certeurope proofs.

        Certeurope generates several documents:
        1. Deposit certificate (proof of sending)
        2. Copy of sent document (archived)
        3. Acknowledgement of receipt (proof of reading)
        4. Presentation certificate (if registered)
        5. Qualified timestamp

        TODO: Implement via Certeurope API
        """
        if not self.missive:
            return []

        external_id = getattr(self.missive, "external_id", None)
        if not external_id or not str(external_id).startswith("certeurope_"):
            return []

        # TODO: Real API call (SOAP or REST depending on version)

        # Simulation
        clock = getattr(self, "_clock", None)
        sent_at = getattr(self.missive, "sent_at", None) or (
            clock() if callable(clock) else datetime.now(timezone.utc)
        )
        expiration = sent_at + timedelta(days=3650)  # 10 years
        proofs = []

        # 1. Deposit certificate (always available)
        proofs.append(
            {
                "type": "deposit_certificate",
                "label": "Deposit Certificate",
                "available": True,
                "url": (f"https://www.certeurope.fr/lre/deposit/{external_id}.pdf"),
                "generated_at": sent_at,
                "expires_at": expiration,
                "format": "pdf",
                "metadata": {
                    "certificate_type": "deposit",
                    "legal_value": "eIDAS probative value",
                    "provider": "certeurope",
                },
            }
        )

        # 2. Signed archived document
        proofs.append(
            {
                "type": "archived_document",
                "label": "Archived Document",
                "available": True,
                "url": (f"https://www.certeurope.fr/lre/archive/{external_id}.pdf"),
                "generated_at": sent_at,
                "expires_at": expiration,
                "format": "pdf",
                "metadata": {
                    "document_type": "archived_signed",
                    "provider": "certeurope",
                },
            }
        )

        # 3. Qualified timestamp
        proofs.append(
            {
                "type": "qualified_timestamp",
                "label": "Qualified Timestamp",
                "available": True,
                "url": (f"https://www.certeurope.fr/lre/timestamp/{external_id}.xml"),
                "generated_at": sent_at,
                "expires_at": expiration,
                "format": "xml",
                "metadata": {
                    "timestamp_type": "qualified_eidas",
                    "provider": "certeurope",
                },
            }
        )

        # 4. Electronic AR (if read)
        read_at = getattr(self.missive, "read_at", None)
        if read_at:
            proofs.append(
                {
                    "type": "acknowledgment_receipt",
                    "label": "Acknowledgement of Receipt",
                    "available": True,
                    "url": (f"https://www.certeurope.fr/lre/ar/{external_id}.pdf"),
                    "generated_at": read_at,
                    "expires_at": expiration,
                    "format": "pdf",
                    "metadata": {
                        "certificate_type": "acknowledgment",
                        "read_date": (
                            read_at.isoformat()
                            if hasattr(read_at, "isoformat")
                            else str(read_at)
                        ),
                        "provider": "certeurope",
                    },
                }
            )
        else:
            proofs.append(
                {
                    "type": "acknowledgment_receipt",
                    "label": "Acknowledgement of Receipt",
                    "available": False,
                    "url": None,
                    "generated_at": None,
                    "expires_at": None,
                    "format": "pdf",
                    "metadata": {
                        "status": "pending",
                        "message": "Waiting for read",
                        "provider": "certeurope",
                    },
                }
            )

        return proofs


__all__ = ["CerteuropeProvider"]

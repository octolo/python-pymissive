"""La Poste provider for postal mail."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..status import MissiveStatus
from .base import BaseProvider
from .base.postal_defaults import (
    POSTAL_DEFAULT_MIME_TYPES,
    POSTAL_ENVELOPE_LIMITS,
)


class LaPosteProvider(BaseProvider):
    """
    La Poste provider.

    Supports:
    - Postal mail (simple, registered, with signature)
    - AR Email (Email with electronic acknowledgment of receipt)
    """

    name = "La Poste"
    display_name = "La Poste"
    supported_types = [
        "POSTAL",
        "POSTAL_REGISTERED",
        "POSTAL_SIGNATURE",
        "EMAIL",
        "LRE",
    ]

    # Postal (courrier simple)
    postal_price = 1.722  # 1.435€ +20%
    postal_page_price_black_white = 0.396
    postal_page_price_color = 0.696
    postal_page_price_single_sided = 0.396
    postal_page_price_duplex = 0.408
    postal_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_allowed_page_formats = ["A4"]
    postal_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_page_limit = 45
    postal_color_printing_available = True
    postal_duplex_printing_available = True
    postal_archiving_duration = 0

    # Postal recommandé (R1)
    postal_registered_price = 6.432  # 5.36€ +20%
    postal_registered_page_price_black_white = 0.396
    postal_registered_page_price_color = 0.696
    postal_registered_page_price_single_sided = 0.396
    postal_registered_page_price_duplex = 0.408
    postal_registered_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_registered_allowed_page_formats = ["A4"]
    postal_registered_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_registered_page_limit = 45
    postal_registered_color_printing_available = True
    postal_registered_duplex_printing_available = True
    postal_registered_archiving_duration = 0

    # Postal signature (R2/R3)
    postal_signature_price = 7.74  # 6.45€ +20%
    postal_signature_page_price_black_white = 0.396
    postal_signature_page_price_color = 0.696
    postal_signature_page_price_single_sided = 0.396
    postal_signature_page_price_duplex = 0.408
    postal_signature_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_signature_allowed_page_formats = ["A4"]
    postal_signature_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_signature_page_limit = 45
    postal_signature_color_printing_available = True
    postal_signature_duplex_printing_available = True
    postal_signature_archiving_duration = 0

    # LRE (électronique)
    lre_price = 4.68  # 3.9€ +20%
    lre_page_price_black_white = 0.0
    lre_page_price_color = 0.0
    lre_page_price_single_sided = 0.0
    lre_page_price_duplex = 0.0
    lre_allowed_attachment_mime_types = ["application/pdf"]
    lre_allowed_page_formats: list[str] = []
    lre_envelope_limits: list[dict[str, Any]] = []
    lre_page_limit = 200
    lre_color_printing_available = False
    lre_duplex_printing_available = False
    lre_archiving_duration = 3650
    # Geographic scopes per service family
    postal_geographic_coverage = ["FR"]  # Postal mail limited to France
    postal_registered_geographic_coverage = ["FR"]
    postal_signature_geographic_coverage = ["FR"]
    email_geographic_coverage = ["*"]  # Email AR not geographically limited
    lre_geographic_coverage = ["*"]  # LRE not geographically limited
    config_keys = ["LAPOSTE_API_KEY"]
    required_packages = ["requests"]
    site_url = "https://www.laposte.fr/"
    description_text = "Registered mail and AR email sending on French territory"

    def _send_postal_service(
        self,
        *,
        service: str,
        is_registered: bool = False,
        requires_signature: bool = False,
        **kwargs,
    ) -> bool:
        """Common postal sending helper."""
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_address"):
            self._update_status(MissiveStatus.FAILED, error_message="Address missing")
            return False

        try:
            # TODO: Integrate with La Poste API
            # import requests
            #
            # api_key = self._config.get('LAPOSTE_API_KEY')
            # address_lines = self.missive.recipient_address.split('\n')
            #
            # response = requests.post(
            #     'https://api.laposte.fr/controladresse/v2/send',
            #     headers={'Authorization': f'Bearer {api_key}'},
            #     json={
            #         'sender': self._config.get('LAPOSTE_SENDER_ADDRESS'),
            #         'recipient': {
            #             'name': address_lines[0] if address_lines else '',
            #             'address': '\n'.join(address_lines[1:]),
            #         },
            #         'content': self.missive.body,
            #         'options': {
            #             'registered': self.missive.is_registered,
            #             'signature_required': self.missive.requires_signature,
            #         }
            #     }
            # )
            #
            # result = response.json()
            # external_id = result.get('tracking_number')

            # Simulation
            external_id = f"lp_{getattr(self.missive, 'id', 'unknown')}"

            letter_type = service.replace("_", " ") or "postal"

            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", f"{letter_type} letter sent via La Poste")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def send_lre(self, **kwargs) -> bool:
        """Send LRE via La Poste (placeholder)."""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        try:
            external_id = f"lp_lre_{getattr(self.missive, 'id', 'unknown')}"
            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", "LRE sent via La Poste")
            return True
        except Exception as exc:
            self._update_status(MissiveStatus.FAILED, error_message=str(exc))
            self._create_event("failed", str(exc))
            return False

    def send_email(self, **kwargs) -> bool:
        """
        Send an AR email (with acknowledgement of receipt) via La Poste.
        La Poste offers an electronic registered email service.
        """
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_email"):
            self._update_status(MissiveStatus.FAILED, error_message="Email missing")
            return False

        try:
            # TODO: Integrate with La Poste Email AR
            # Simulation
            external_id = f"lp_email_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT,
                provider=f"{self.name} Email AR",
                external_id=external_id,
            )
            self._create_event("sent", "AR email sent via La Poste")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Validate La Poste webhook signature."""
        # To be implemented according to La Poste API documentation
        return True, ""

    def extract_missive_id(
        self, payload: Any, *, missive_type: Optional[str] = None, **kwargs: Any
    ) -> Optional[str]:
        """Extract missive ID from La Poste webhook."""
        if isinstance(payload, dict):
            result = payload.get("reference") or payload.get("tracking_number")
            return str(result) if result else None
        return None

    def extract_event_type(self, payload: Any) -> str:
        """Extract event type from La Poste webhook."""
        if isinstance(payload, dict):
            result = payload.get("status", "unknown")
            return str(result) if result else "unknown"
        return "unknown"

    def get_proofs_of_delivery(self, service_type: Optional[str] = None) -> list:
        """
        Get all La Poste proofs.

        La Poste generates several documents according to service:
        - Simple mail: Deposit proof
        - Registered mail R1: Deposit proof + AR + delivery notice
        - Registered mail R2/R3: Deposit proof + AR + signature + scanned copy
        - AR Email: Electronic acknowledgement of receipt

        TODO: Implement via La Poste API
        """
        if not self.missive:
            return []

        external_id = getattr(self.missive, "external_id", None)
        if not external_id or not str(external_id).startswith("lp_"):
            return []

        # Determine the service type
        if not service_type:
            missive_type = getattr(self.missive, "missive_type", "")
            if missive_type == "EMAIL":
                service_type = "email_ar"
            elif getattr(self.missive, "requires_signature", False):
                service_type = "postal_signature"
            elif getattr(self.missive, "is_registered", False):
                service_type = "postal_registered"
            else:
                service_type = "postal"

        # TODO: Real API call

        # Simulation
        clock = getattr(self, "_clock", None)
        sent_at = getattr(self.missive, "sent_at", None) or (
            clock() if callable(clock) else datetime.now(timezone.utc)
        )
        tracking_number = str(external_id).replace("lp_", "")
        proofs = []

        # 1. Deposit proof (always available)
        proofs.append(
            {
                "type": "deposit_receipt",
                "label": "Deposit Proof",
                "available": True,
                "url": f"https://www.laposte.fr/suivi/proof/deposit/{tracking_number}.pdf",
                "generated_at": sent_at,
                "expires_at": None,
                "format": "pdf",
                "metadata": {
                    "proof_type": "deposit",
                    "provider": "laposte",
                    "tracking_number": tracking_number,
                },
            }
        )

        # 2. Document copy (if postal mail)
        if "postal" in service_type:
            proofs.append(
                {
                    "type": "document_copy",
                    "label": "Mail Copy",
                    "available": True,
                    "url": f"https://www.laposte.fr/suivi/document/{tracking_number}.pdf",
                    "generated_at": sent_at,
                    "expires_at": None,
                    "format": "pdf",
                    "metadata": {
                        "document_type": "copy",
                        "provider": "laposte",
                    },
                }
            )

        # 3. AR (if registered and delivered)
        if getattr(self.missive, "is_registered", False):
            delivered_at = getattr(self.missive, "delivered_at", None)
            if delivered_at:
                proofs.append(
                    {
                        "type": "acknowledgment_receipt",
                        "label": "Acknowledgement of Receipt",
                        "available": True,
                        "url": f"https://www.laposte.fr/suivi/ar/{tracking_number}.pdf",
                        "generated_at": delivered_at,
                        "expires_at": None,
                        "format": "pdf",
                        "metadata": {
                            "ar_type": (
                                "R1"
                                if not getattr(
                                    self.missive, "requires_signature", False
                                )
                                else "R2/R3"
                            ),
                            "delivery_date": (
                                delivered_at.isoformat()
                                if hasattr(delivered_at, "isoformat")
                                else str(delivered_at)
                            ),
                            "provider": "laposte",
                        },
                    }
                )

        return proofs

    def get_postal_service_info(self) -> Dict[str, Any]:
        """Return detailed postal service capabilities."""
        return {
            "provider": self.name,
            "services": ["postal", "postal_registered", "postal_signature"],
            "max_attachment_size_mb": 10.0,
            "max_attachment_size_bytes": 10 * 1024 * 1024,
            "allowed_attachment_mime_types": self.postal_allowed_attachment_mime_types,
            "geographic_coverage": self.postal_geographic_coverage,
            "features": [
                "Color printing",
                "Duplex printing (par défaut)",
                "Optional address sheet",
                "Electronic acknowledgement of receipt",
            ],
        }

    def get_service_status(self) -> Dict:
        """
        Gets La Poste status and credits.

        La Poste uses prepaid credits.

        Returns:
            Dict with status, credits, etc.
        """
        return self._build_service_status_payload(
            rate_limits={"per_second": 2, "per_minute": 120},
            warnings=["La Poste API not implemented - uncomment the code"],
            details={
                "refill_url": "https://developer.laposte.fr/",
                "api_docs": "https://developer.laposte.fr/products",
            },
            sla={"uptime_percentage": 99.9},
        )


__all__ = ["LaPosteProvider"]

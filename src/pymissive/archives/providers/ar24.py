"""AR24 provider for electronic registered letters (LRE)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..status import MissiveStatus
from .base import BaseProvider


class AR24Provider(BaseProvider):
    """
    AR24 provider (Electronic Registered Letter).
    Simulates behaviour until real API integration is implemented.
    """

    name = "ar24"
    display_name = "AR24 (LRE)"
    supported_types = ["POSTAL", "POSTAL_REGISTERED", "LRE"]
    services = ["lre", "postal_registered"]
    # Geographic scope
    lre_geo = ["Europe"]
    postal_geo = ["Europe"]
    config_keys = ["AR24_API_TOKEN", "AR24_API_URL", "AR24_SENDER_ID"]
    required_packages = ["requests"]
    site_url = "https://www.ar24.fr/"
    description_text = "Electronic registered email (LRE) with legal value"

    def send_postal(self, **kwargs) -> bool:
        """Send an LRE via AR24 (simulated)."""
        risk = self.calculate_postal_delivery_risk()
        if not risk.get("should_send", True):
            recommendations = risk.get("recommendations", [])
            error_message = next(
                (rec for rec in recommendations if rec), "Postal delivery blocked"
            )
            self._update_status(MissiveStatus.FAILED, error_message=error_message)
            return False

        simulated_id = f"ar24_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=simulated_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """Check the LRE status (not implemented)."""
        return None

    def get_proofs_of_delivery(self, service_type: Optional[str] = None) -> list:
        """Return simulated AR24 proofs."""
        if not self.missive:
            return []

        external_id = getattr(self.missive, "external_id", "")
        if not external_id or not str(external_id).startswith("ar24_"):
            return []

        sent_at = getattr(self.missive, "sent_at", None)
        read_at = getattr(self.missive, "read_at", None)

        proofs = [
            {
                "type": "deposit_certificate",
                "label": "Deposit Certificate",
                "available": True,
                "url": f"https://www.ar24.fr/certificate/deposit/{external_id}.pdf",
                "generated_at": sent_at,
                "expires_at": None,
                "format": "pdf",
                "metadata": {
                    "certificate_type": "deposit",
                    "provider": "ar24",
                },
            },
            {
                "type": "sent_document",
                "label": "Sent Document",
                "available": True,
                "url": f"https://www.ar24.fr/mail/{external_id}/document.pdf",
                "generated_at": sent_at,
                "expires_at": None,
                "format": "pdf",
                "metadata": {
                    "document_type": "sent_copy",
                    "provider": "ar24",
                },
            },
        ]

        if read_at:
            proofs.append(
                {
                    "type": "acknowledgment_receipt",
                    "label": "Acknowledgement of Receipt",
                    "available": True,
                    "url": f"https://www.ar24.fr/certificate/ar/{external_id}.pdf",
                    "generated_at": read_at,
                    "expires_at": None,
                    "format": "pdf",
                    "metadata": {
                        "certificate_type": "acknowledgment",
                        "read_date": read_at.isoformat(),
                        "provider": "ar24",
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
                        "message": "Awaiting recipient read confirmation",
                        "provider": "ar24",
                    },
                }
            )

        return proofs

    def get_postal_service_info(self) -> Dict[str, Any]:
        base = super().get_postal_service_info()
        base.update(
            {
                "credits": None,
                "warnings": base.get("warnings", []),
                "details": {
                    "provider": "ar24",
                    "jurisdiction": "France",
                },
            }
        )
        return base

    def calculate_postal_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Evaluate whether the missive can be safely sent via AR24."""

        def _handler(
            target_missive: Any,
            factors: Dict[str, Any],
            recommendations: List[str],
            total_risk: float,
        ) -> Dict[str, Any]:
            recipient = getattr(target_missive, "recipient", None)
            risk_total = total_risk
            if not recipient:
                recommendations.append("Recipient not defined")
                risk_total = 100.0
            else:
                recipient_email = getattr(recipient, "email", None)
                if not recipient_email:
                    recommendations.append("Recipient email required for AR24 LRE")
                    risk_total = 100.0
                else:
                    factors["recipient_email"] = recipient_email

                address_line1 = getattr(recipient, "address_line1", None)
                postal_code = getattr(recipient, "postal_code", None)
                city = getattr(recipient, "city", None)

                if not address_line1:
                    recommendations.append("Postal address missing (recommended for AR24)")
                    risk_total += 20
                if not postal_code or not city:
                    recommendations.append("Postal code and city missing")
                    risk_total += 20

            service_check = self.check_service_availability()
            factors["service_availability"] = service_check
            if service_check.get("is_available") is False:
                risk_total += 20
                recommendations.append("Service temporarily unavailable")

            risk_score = min(int(risk_total), 100)
            risk_level = self._calculate_risk_level(risk_score)

            should_send = (
                risk_score < 70
                and "Recipient email required for AR24 LRE" not in recommendations
            )

            return {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "factors": factors,
                "recommendations": recommendations,
                "should_send": should_send,
            }

        return self._run_risk_analysis(missive, _handler)


__all__ = ["AR24Provider"]

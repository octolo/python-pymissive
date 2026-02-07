"""Maileva provider for postal mail and registered mail."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, cast

from ..status import MissiveStatus
from .base import BaseProvider
from .base.postal_defaults import (
    POSTAL_DEFAULT_MIME_TYPES,
    POSTAL_ENVELOPE_LIMITS,
)


class MailevaProvider(BaseProvider):
    """
    Maileva provider (Docaposte/La Poste group).

    Maileva is a subsidiary of Docaposte (La Poste group) offering
    electronic postal mail services for businesses.

    Supports:
    - Postal mail (simple, registered, signature)
    - Qualified and standard electronic registered letters (LRE / ERE)
    - Document archiving
    """

    name = "Maileva"
    display_name = "Maileva"
    supported_types = [
        "POSTAL",
        "POSTAL_REGISTERED",
        "POSTAL_SIGNATURE",
        "LRE",
        "LRE_QUALIFIED",
        "ERE",
    ]
    # Postal simple
    postal_price = 1.435
    postal_page_price_black_white = 0.33
    postal_page_price_color = 0.58
    postal_page_price_single_sided = 0.33
    postal_page_price_duplex = 0.34
    postal_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_allowed_page_formats = ["A4"]
    postal_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_page_limit = 45
    postal_color_printing_available = True
    postal_duplex_printing_available = True
    postal_archiving_duration = 0

    # Postal recommandé
    postal_registered_price = 5.36
    postal_registered_page_price_black_white = 0.33
    postal_registered_page_price_color = 0.58
    postal_registered_page_price_single_sided = 0.33
    postal_registered_page_price_duplex = 0.34
    postal_registered_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_registered_allowed_page_formats = ["A4"]
    postal_registered_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_registered_page_limit = 45
    postal_registered_color_printing_available = True
    postal_registered_duplex_printing_available = True
    postal_registered_archiving_duration = 0

    # Postal signature
    postal_signature_price = 6.45
    postal_signature_page_price_black_white = 0.33
    postal_signature_page_price_color = 0.58
    postal_signature_page_price_single_sided = 0.33
    postal_signature_page_price_duplex = 0.34
    postal_signature_allowed_attachment_mime_types = list(POSTAL_DEFAULT_MIME_TYPES)
    postal_signature_allowed_page_formats = ["A4"]
    postal_signature_envelope_limits = [limit.copy() for limit in POSTAL_ENVELOPE_LIMITS]
    postal_signature_page_limit = 45
    postal_signature_color_printing_available = True
    postal_signature_duplex_printing_available = True
    postal_signature_archiving_duration = 0

    # LRE standard
    lre_price = 3.9
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
    lre_archiving_duration = 3650  # 10 years

    # LRE qualifiée
    lre_qualified_price = 6.2
    lre_qualified_page_price_black_white = 0.0
    lre_qualified_page_price_color = 0.0
    lre_qualified_page_price_single_sided = 0.0
    lre_qualified_page_price_duplex = 0.0
    lre_qualified_allowed_attachment_mime_types = ["application/pdf"]
    lre_qualified_allowed_page_formats: list[str] = []
    lre_qualified_envelope_limits: list[dict[str, Any]] = []
    lre_qualified_page_limit = 200
    lre_qualified_color_printing_available = False
    lre_qualified_duplex_printing_available = False
    lre_qualified_archiving_duration = 3650

    # Envoi recommandé électronique
    ere_price = 2.8
    ere_page_price_black_white = 0.0
    ere_page_price_color = 0.0
    ere_page_price_single_sided = 0.0
    ere_page_price_duplex = 0.0
    ere_allowed_attachment_mime_types = ["application/pdf", "application/xml"]
    ere_allowed_page_formats: list[str] = []
    ere_envelope_limits: list[dict[str, Any]] = []
    ere_page_limit = 200
    ere_color_printing_available = False
    ere_duplex_printing_available = False
    ere_archiving_duration = 1825  # 5 years
    # Geographic scopes per service family
    postal_geographic_coverage = ["FR"]  # Postal mail limited to France
    postal_registered_geographic_coverage = ["FR"]
    postal_signature_geographic_coverage = ["FR"]
    lre_geographic_coverage = ["FR"]  # LRE limited to France
    lre_qualified_geographic_coverage = ["FR"]
    ere_geographic_coverage = ["FR"]  # ERE limited to France (Docaposte trust scope)
    email_geographic_coverage = ["FR"]
    config_keys = [
        "MAILEVA_CLIENTID",
        "MAILEVA_SECRET",
        "MAILEVA_USERNAME",
        "MAILEVA_PASSWORD",
    ]
    required_packages = ["requests"]
    site_url = "https://www.maileva.com/"
    documentation_url = "https://www.maileva.com/developpeur"
    description_text = "Electronic postal mail and registered mail services"

    # API endpoints
    API_BASE_PRODUCTION = "https://api.maileva.com"
    API_BASE_SANDBOX = "https://api.sandbox.maileva.net"
    AUTH_BASE_PRODUCTION = "https://connexion.maileva.com"
    AUTH_BASE_SANDBOX = "https://connexion.sandbox.maileva.net"

    def _get_api_base(self) -> str:
        """Get API base URL based on sandbox mode."""
        sandbox = self._config.get("MAILEVA_SANDBOX", False)
        return self.API_BASE_SANDBOX if sandbox else self.API_BASE_PRODUCTION

    def _get_auth_base(self) -> str:
        """Get authentication base URL based on sandbox mode."""
        sandbox = self._config.get("MAILEVA_SANDBOX", False)
        return self.AUTH_BASE_SANDBOX if sandbox else self.AUTH_BASE_PRODUCTION

    def _get_access_token(self) -> Optional[str]:
        """
        Get OAuth access token from Maileva.

        Maileva uses OAuth 2.0 with client credentials flow.
        """
        try:
            import requests

            auth_url = f"{self._get_auth_base()}/auth/realms/services/protocol/openid-connect/token"
            client_id = self._config.get("MAILEVA_CLIENTID")
            client_secret = self._config.get("MAILEVA_SECRET")
            username = self._config.get("MAILEVA_USERNAME")
            password = self._config.get("MAILEVA_PASSWORD")

            if not all([client_id, client_secret, username, password]):
                return None

            # OAuth 2.0 client credentials + resource owner password credentials
            response = requests.post(
                auth_url,
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                },
                timeout=10,
            )
            response.raise_for_status()
            token_data = cast(Dict[str, Any], response.json())
            access_token = token_data.get("access_token")
            return str(access_token) if isinstance(access_token, str) else None

        except Exception as e:
            self._create_event("error", f"Failed to get access token: {e}")
            return None

    def _send_postal_service(
        self,
        *,
        service: str,
        is_registered: bool = False,
        requires_signature: bool = False,
        **kwargs,
    ) -> bool:
        """Internal helper to send any postal variation."""
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_address"):
            self._update_status(MissiveStatus.FAILED, error_message="Address missing")
            return False

        try:
            access_token = self._get_access_token()
            if not access_token:
                self._update_status(
                    MissiveStatus.FAILED, error_message="Failed to authenticate"
                )
                return False

            # TODO: Implement API call
            # api_base = self._get_api_base()
            # Choose API version based on service type
            # if is_registered or requires_signature:
            #     sendings_url = f"{api_base}/registered_mail/v4/sendings"
            # else:
            #     sendings_url = f"{api_base}/mail/v2/sendings"
            #
            # headers = {
            #     "Authorization": f"Bearer {access_token}",
            #     "Content-Type": "application/json",
            # }
            #
            # recipient_address = self._get_missive_value("recipient_address", "")
            # address_lines = recipient_address.split("\n") if recipient_address else []
            # sending_data = {
            #     "sender": {...},
            #     "recipient": {...},
            #     "options": {...},
            # }
            # TODO: Add document upload
            # TODO: Add recipient details
            # TODO: Submit sending

            # Simulation for now
            external_id = f"mv_{getattr(self.missive, 'id', 'unknown')}"

            letter_type = service.replace("_", " ")
            if not letter_type:
                letter_type = "postal"

            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", f"{letter_type} letter sent via Maileva")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def _send_electronic_registered(self, service: str, *, description: str) -> bool:
        """Simulate electronic registered (LRE/ERE) sending."""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        recipient_email = self._get_missive_value("recipient_email")
        if not recipient_email:
            self._update_status(
                MissiveStatus.FAILED, error_message="Recipient email missing"
            )
            return False

        try:
            external_id = f"{service}_{getattr(self.missive, 'id', 'unknown')}"
            self._update_status(
                MissiveStatus.SENT, provider=self.name, external_id=external_id
            )
            self._create_event("sent", f"{description} sent via Maileva")
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self._update_status(MissiveStatus.FAILED, error_message=str(exc))
            self._create_event("failed", str(exc))
            return False

    def send_lre(self, **kwargs) -> bool:
        """Send a standard LRE via Maileva."""
        return self._send_electronic_registered("lre", description="LRE", **kwargs)

    def send_lre_qualified(self, **kwargs) -> bool:
        """Send a qualified LRE via Maileva."""
        return self._send_electronic_registered(
            "lre_qualified", description="Qualified LRE", **kwargs
        )

    def send_ere(self, **kwargs) -> bool:
        """Send an electronic registered email via Maileva."""
        return self._send_electronic_registered("ere", description="ERE", **kwargs)

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Validate Maileva webhook signature."""
        # TODO: Implement according to Maileva webhook documentation
        # Maileva webhooks may use HMAC or OAuth signature
        return True, ""

    def extract_missive_id(
        self, payload: Any, *, missive_type: Optional[str] = None, **kwargs: Any
    ) -> Optional[str]:
        """Extract missive ID from Maileva webhook."""
        if isinstance(payload, dict):
            result = (
                payload.get("sending_id")
                or payload.get("reference")
                or payload.get("id")
            )
            return str(result) if result else None
        return None

    def extract_event_type(self, payload: Any) -> str:
        """Extract event type from Maileva webhook."""
        if isinstance(payload, dict):
            result = payload.get("status") or payload.get("event_type") or "unknown"
            return str(result) if result else "unknown"
        return "unknown"

    def get_proofs_of_delivery(self, service_type: Optional[str] = None) -> list:
        """
        Get all Maileva proofs.

        Maileva generates:
        - Deposit proof (global_deposit_proofs)
        - Delivery proof (if registered)
        - Signature proof (if signature required)
        """
        if not self.missive:
            return []

        external_id = getattr(self.missive, "external_id", None)
        if not external_id or not str(external_id).startswith("mv_"):
            return []

        try:
            access_token = self._get_access_token()
            if not access_token:
                return []

            api_base = self._get_api_base()
            sending_id = str(external_id).replace("mv_", "")

            # TODO: Implement real API call
            # proofs_url = f"{api_base}/registered_mail/v4/global_deposit_proofs"
            # headers = {"Authorization": f"Bearer {access_token}"}
            # response = requests.get(
            #     proofs_url,
            #     params={"sending_id": sending_id},
            #     headers=headers,
            #     timeout=10,
            # )
            # response.raise_for_status()
            # proofs_data = response.json()

            # Simulation
            clock = getattr(self, "_clock", None)
            sent_at = getattr(self.missive, "sent_at", None) or (
                clock() if callable(clock) else datetime.now(timezone.utc)
            )

            proofs = [
                {
                    "type": "deposit_receipt",
                    "label": "Deposit Proof",
                    "available": True,
                    "url": f"{api_base}/registered_mail/v4/global_deposit_proofs/{sending_id}",
                    "generated_at": sent_at,
                    "expires_at": None,
                    "format": "pdf",
                    "metadata": {
                        "proof_type": "deposit",
                        "provider": "maileva",
                        "sending_id": sending_id,
                    },
                }
            ]

            # Add delivery proof if registered
            if getattr(self.missive, "is_registered", False):
                delivered_at = getattr(self.missive, "delivered_at", None)
                if delivered_at:
                    proofs.append(
                        {
                            "type": "acknowledgment_receipt",
                            "label": "Acknowledgement of Receipt",
                            "available": True,
                            "url": f"{api_base}/registered_mail/v4/sendings/{sending_id}/proofs/ar",
                            "generated_at": delivered_at,
                            "expires_at": None,
                            "format": "pdf",
                            "metadata": {
                                "proof_type": "ar",
                                "provider": "maileva",
                                "sending_id": sending_id,
                            },
                        }
                    )

            return proofs

        except Exception as e:
            self._create_event("error", f"Failed to get proofs: {e}")
            return []

    def get_service_status(self) -> Dict:
        """
        Gets Maileva status and credits.

        Maileva uses prepaid credits and subscription model.

        Returns:
            Dict with status, credits, etc.
        """
        return self._build_service_status_payload(
            rate_limits={"per_second": 5, "per_minute": 300},
            warnings=["Maileva API not fully implemented - uncomment the code"],
            details={
                "refill_url": "https://www.maileva.com/",
                "api_docs": "https://www.maileva.com/developpeur",
                "sandbox_url": "https://secure2.recette.maileva.com/",
            },
            sla={"uptime_percentage": 99.5},
        )

    def get_postal_service_info(self) -> Dict[str, Any]:
        """Get postal service information."""
        return {
            "provider": self.name,
            "services": ["postal", "postal_registered", "postal_signature"],
            "max_attachment_size_mb": 10.0,
            "max_attachment_size_bytes": 10 * 1024 * 1024,
            "allowed_attachment_mime_types": self.postal_allowed_attachment_mime_types,
            "geographic_coverage": self.postal_geographic_coverage,
            "features": [
                "Color printing",
                "Duplex printing",
                "Optional address sheet",
                "Document archiving",
            ],
        }

    def get_lre_service_info(self) -> Dict[str, Any]:
        """Describe Maileva LRE (standard) features."""
        return {
            "provider": self.name,
            "services": ["lre"],
            "geographic_coverage": self.lre_geographic_coverage,
            "features": [
                "Electronic registered letter creation",
                "Delivery tracking and proofs",
                "Integration via Maileva API catalogue",
            ],
            "details": {
                "catalog_url": "https://www.maileva.com/catalogue-api/envoi-et-suivi-ere-simples/",
            },
        }

    def get_lre_qualified_service_info(self) -> Dict[str, Any]:
        """Describe qualified LRE (Docaposte trust service) capabilities."""
        return {
            "provider": self.name,
            "services": ["lre_qualified"],
            "geographic_coverage": self.lre_qualified_geographic_coverage,
            "features": [
                "Qualified LRE generation (eIDAS-compliant)",
                "Qualified electronic signature + timestamp",
                "Full traceability with legal proofs",
            ],
            "details": {
                "catalog_url": "https://www.maileva.com/catalogue-api/envoi-et-suivi-de-lre-qualifiees/",
            },
        }

    def get_ere_service_info(self) -> Dict[str, Any]:
        """Describe simple electronic registered email (ERE) capabilities."""
        return {
            "provider": self.name,
            "services": ["ere"],
            "geographic_coverage": self.ere_geographic_coverage,
            "features": [
                "Electronic registered email dispatch",
                "Acknowledgement of receipt via Maileva",
                "API monitoring and follow-up",
            ],
            "details": {
                "catalog_url": "https://www.maileva.com/catalogue-api/envoi-et-suivi-ere-simples/",
            },
        }


__all__ = ["MailevaProvider"]

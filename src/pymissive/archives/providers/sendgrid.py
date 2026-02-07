"""SendGrid email provider."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict, Optional, Tuple

from .base import BaseProvider


class SendGridProvider(BaseProvider):
    """SendGrid email provider."""

    name = "SendGrid"
    display_name = "SendGrid"
    supported_types = ["EMAIL", "EMAIL_MARKETING"]
    # Geographic scope and pricing
    email_geographic_coverage = ["*"]
    email_geo = email_geographic_coverage
    email_marketing_geographic_coverage = ["*"]
    email_marketing_geo = email_marketing_geographic_coverage
    email_price = 0.9  # Similar to Mailgun baseline
    email_marketing_price = 0.15  # Marketing credits slightly higher
    email_marketing_max_attachment_size_mb = 10
    email_marketing_allowed_attachment_mime_types = [
        "text/html",
        "image/jpeg",
        "image/png",
    ]
    config_keys = ["SENDGRID_API_KEY"]
    required_packages = ["sendgrid"]
    site_url = "https://sendgrid.com/"
    status_url = "https://status.sendgrid.com/"
    documentation_url = "https://docs.sendgrid.com/"
    description_text = "Transactional and marketing email (Twilio SendGrid)"

    def send_email(self, **kwargs) -> bool:
        """Sends email via SendGrid API."""
        return self._send_email_simulation(
            prefix="sg", event_message="Email sent via SendGrid"
        )

    def send_email_marketing(self, **kwargs) -> bool:
        """Marketing campaigns follow the transactional send path."""
        return self.send_email(**kwargs)

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Validate SendGrid webhook signature."""
        webhook_key = self._config.get("SENDGRID_WEBHOOK_KEY")
        if not webhook_key:
            return True, ""  # No validation

        sig_header = "HTTP_X_TWILIO_EMAIL_EVENT_WEBHOOK_SIGNATURE"
        signature = headers.get(sig_header, "")
        ts_header = "HTTP_X_TWILIO_EMAIL_EVENT_WEBHOOK_TIMESTAMP"
        timestamp = headers.get(ts_header, "")

        if not signature or not timestamp:
            return False, "Signature or timestamp missing"

        # Reconstruct the signature
        payload_str = json.dumps(payload, separators=(",", ":"))
        signed_payload = timestamp + payload_str

        expected_signature = base64.b64encode(
            hmac.new(
                webhook_key.encode(), signed_payload.encode(), hashlib.sha256
            ).digest()
        ).decode()

        if hmac.compare_digest(signature, expected_signature):
            return True, ""
        return False, "Signature does not match"

    def validate_email_marketing_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Marketing webhooks reuse the same verification."""
        return self.validate_webhook_signature(
            payload, headers, missive_type="EMAIL_MARKETING", **kwargs
        )

    def extract_email_missive_id(self, payload: Any) -> Optional[str]:
        """Extract missive ID from SendGrid webhook."""
        # SendGrid sends an array of events
        if isinstance(payload, list) and len(payload) > 0:
            event = payload[0]
            if isinstance(event, dict):
                result = event.get("missive_id") or event.get("custom_args", {}).get(
                    "missive_id"
                )
                return str(result) if result else None
        elif isinstance(payload, dict):
            result = payload.get("missive_id") or payload.get("custom_args", {}).get(
                "missive_id"
            )
            return str(result) if result else None
        return None

    def extract_email_marketing_missive_id(self, payload: Any) -> Optional[str]:
        """Reuse transactional ID extraction."""
        return self.extract_email_missive_id(payload)

    def extract_event_type(self, payload: Any) -> str:
        """Extract event type from SendGrid webhook."""
        if isinstance(payload, list) and len(payload) > 0:
            event = payload[0]
            if isinstance(event, dict):
                result = event.get("event", "unknown")
                return str(result) if result else "unknown"
        elif isinstance(payload, dict):
            result = payload.get("event", "unknown")
            return str(result) if result else "unknown"
        return "unknown"

    def handle_email_marketing_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Delegate marketing webhook handling to transactional handler."""
        return self.handle_email_webhook(payload, headers)

    def get_service_status(self) -> Dict:
        """
        Gets SendGrid status and credits.

        Returns:
            Dict with status, credits, etc.
        """
        return self._build_generic_service_status(
            credits_type="emails",
            credits_currency="emails",
            rate_limits={"per_second": 10, "per_minute": 600},
            warnings=["SendGrid API not implemented - uncomment the code"],
            details={
                "status_page": "https://status.sendgrid.com/",
                "api_docs": (
                    "https://docs.sendgrid.com/api-reference/"
                    "stats/retrieve-email-statistics"
                ),
            },
            sla={"uptime_percentage": 99.99, "response_time_ms": 100},
        )


__all__ = ["SendGridProvider"]

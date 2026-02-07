"""Mailgun email provider."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, Optional, Tuple

from .base import BaseProvider


class MailgunProvider(BaseProvider):
    """Mailgun provider (Email only)."""

    name = "Mailgun"
    display_name = "Mailgun"
    supported_types = ["EMAIL", "EMAIL_MARKETING"]
    # Geographic scope and pricing
    email_geographic_coverage = ["*"]
    email_geo = email_geographic_coverage
    email_marketing_geographic_coverage = ["*"]
    email_marketing_geo = email_marketing_geographic_coverage
    email_price = 0.90  # $0.80/100 emails ~ €0.009 -> scaled to €0.009, rounding
    email_marketing_price = 0.12  # Marketing campaigns at slightly higher cost
    email_marketing_max_attachment_size_mb = 10
    email_marketing_allowed_attachment_mime_types = [
        "text/html",
        "image/jpeg",
        "image/png",
    ]
    config_keys = ["MAILGUN_API_KEY", "MAILGUN_DOMAIN"]
    required_packages = ["mailgun"]
    site_url = "https://www.mailgun.com/"
    status_url = "https://status.mailgun.com/"
    documentation_url = "https://documentation.mailgun.com/"
    description_text = (
        "Transactional email service with advanced validation and routing"
    )

    def send_email(self, **kwargs) -> bool:
        """Send via Mailgun API"""
        return self._send_email_simulation(
            prefix="mg", event_message="Email sent via Mailgun"
        )

    def send_email_marketing(self, **kwargs) -> bool:
        """Reuse transactional pipeline for marketing blasts."""
        return self.send_email(**kwargs)

    def validate_webhook_signature(
        self,
        payload: Any,
        headers: Dict[str, str],
        *,
        missive_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """Validate Mailgun webhook signature."""
        api_key = self._config.get("MAILGUN_API_KEY")
        if not api_key:
            return True, ""

        signature_data = payload.get("signature", {})
        timestamp = signature_data.get("timestamp", "")
        token = signature_data.get("token", "")
        signature = signature_data.get("signature", "")

        expected_signature = hmac.new(
            api_key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(signature, expected_signature):
            return True, ""
        return False, "Signature does not match"

    def extract_email_missive_id(self, payload: Any) -> Optional[str]:
        """Extract missive ID from Mailgun webhook."""
        if isinstance(payload, dict):
            event_data = payload.get("event-data", {})
            if isinstance(event_data, dict):
                user_variables = event_data.get("user-variables", {})
                if isinstance(user_variables, dict):
                    result = user_variables.get("missive_id")
                    return str(result) if result else None
        return None

    def extract_event_type(self, payload: Any) -> str:
        """Extract event type from Mailgun webhook."""
        if isinstance(payload, dict):
            event_data = payload.get("event-data", {})
            if isinstance(event_data, dict):
                result = event_data.get("event", "unknown")
                return str(result) if result else "unknown"
        return "unknown"

    def get_service_status(self) -> Dict:
        """
        Gets Mailgun status and credits.

        Mailgun charges per email sent.

        Returns:
            Dict with status, credits, etc.
        """
        return self._build_generic_service_status(
            credits_type="emails",
            credits_currency="emails",
            rate_limits={"per_second": 100, "per_minute": 6000},
            warnings=["Mailgun API not implemented - uncomment the code"],
            details={
                "status_page": "https://status.mailgun.com/",
                "api_docs": "https://documentation.mailgun.com/en/latest/api-stats.html",
            },
            sla={"uptime_percentage": 99.99},
        )


__all__ = ["MailgunProvider"]

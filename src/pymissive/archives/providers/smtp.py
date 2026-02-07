"""Generic SMTP provider without Django dependencies."""

from __future__ import annotations

import smtplib
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

from ..status import MissiveStatus
from .base import BaseProvider
from .base.email_message import build_email_message


class SMTPProvider(BaseProvider):
    """Simple SMTP provider supporting transactional and marketing emails."""

    name = "smtp"
    display_name = "SMTP"
    supported_types = ["EMAIL", "EMAIL_MARKETING"]
    config_keys = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT_SECONDS",
        "DEFAULT_FROM_EMAIL",
    ]
    required_packages: List[str] = []
    description_text = (
        "Direct SMTP integration with optional TLS/SSL and inline attachment support."
    )

    # Geographic scopes + pricing baseline
    email_geographic_coverage = ["*"]
    email_geo = email_geographic_coverage
    email_price = 0.0  # delegated to provider pricing
    email_marketing_geographic_coverage = ["*"]
    email_marketing_geo = email_marketing_geographic_coverage
    email_marketing_price = 0.0

    def validate(self) -> Tuple[bool, str]:
        """Ensure mandatory connection settings exist."""
        host = self._config.get("SMTP_HOST")
        port = self._config.get("SMTP_PORT")
        if not host or not port:
            return False, "SMTP_HOST and SMTP_PORT must be configured"

        if "DEFAULT_FROM_EMAIL" not in self._config:
            sender_addr = self._get_missive_value(
                "sender_email"
            ) or self._get_missive_value("sender")
            self._raw_config["DEFAULT_FROM_EMAIL"] = (
                sender_addr if isinstance(sender_addr, str) else "noreply@example.com"
            )
            self._config = self._filter_config(self._raw_config)

        return super().validate()

    def send_email(self, **kwargs: Any) -> bool:
        """Send an email via configured SMTP server."""
        recipient = self._get_missive_value(
            "get_recipient_email"
        ) or self._get_missive_value("recipient_email")
        if not recipient:
            self._update_status(
                MissiveStatus.FAILED, error_message="Recipient email missing"
            )
            return False

        message = self._build_message(recipient)

        try:
            with self._smtp_connection() as smtp:
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            return self._handle_send_error(exc)

        external_id = f"smtp_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT, provider=self.name, external_id=external_id
        )
        self._create_event("sent", "Email sent via SMTP")
        return True

    def send_email_marketing(self, **kwargs: Any) -> bool:
        """Marketing campaigns reuse the same pipeline."""
        return self.send_email(**kwargs)

    def get_email_service_info(self) -> Dict[str, Any]:
        info = super().get_email_service_info()
        info["details"].update(
            {
                "host": self._config.get("SMTP_HOST"),
                "port": self._config.get("SMTP_PORT"),
                "use_tls": self._bool_config("SMTP_USE_TLS", False),
                "use_ssl": self._bool_config("SMTP_USE_SSL", False),
            }
        )
        info["warnings"] = []
        return info

    def get_email_marketing_service_info(self) -> Dict[str, Any]:
        return self.get_email_service_info()

    def get_service_status(self) -> Dict[str, Any]:
        """Return lightweight availability info."""
        service_info = self.get_email_service_info()
        return self._build_generic_service_status(
            status="operational",
            is_available=True,
            credits_type="unlimited",
            rate_limits={},
            warnings=service_info.get("warnings"),
            details=service_info.get("details"),
        )

    def cancel_email(self, **kwargs: Any) -> bool:
        """SMTP has no notion of cancel."""
        return False

    def cancel_email_marketing(self, **kwargs: Any) -> bool:
        return False

    def validate_email_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """SMTP providers do not expose webhooks by default."""
        return True, ""

    validate_email_marketing_webhook_signature = validate_email_webhook_signature

    def handle_email_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        return False, "SMTP provider has no webhooks", None

    handle_email_marketing_webhook = handle_email_webhook

    def extract_email_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        return None

    extract_email_marketing_missive_id = extract_email_missive_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_message(self, recipient: str) -> EmailMessage:
        from_email = self._config.get("DEFAULT_FROM_EMAIL", "noreply@example.com")
        return build_email_message(self, recipient, from_email=from_email)

    @contextmanager
    def _smtp_connection(self):
        host = str(self._config.get("SMTP_HOST"))
        port = int(self._config.get("SMTP_PORT"))
        timeout = float(self._config.get("SMTP_TIMEOUT_SECONDS", 10))
        use_ssl = self._bool_config("SMTP_USE_SSL", False)
        use_tls = self._bool_config("SMTP_USE_TLS", False)

        if use_ssl:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
            if use_tls:
                smtp.starttls()

        username = self._config.get("SMTP_USERNAME")
        password = self._config.get("SMTP_PASSWORD")
        if username and password:
            smtp.login(username, password)

        try:
            yield smtp
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()

    def _bool_config(self, key: str, default: bool) -> bool:
        """Convert config value to boolean."""
        value = self._raw_config.get(key, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


__all__ = ["SMTPProvider"]

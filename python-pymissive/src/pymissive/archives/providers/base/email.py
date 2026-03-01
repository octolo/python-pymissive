"""Email provider mixin without Django dependencies."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ...status import MissiveStatus
from ._attachments import (
    AttachmentMimeTypeMixin,
    attachment_check_empty_result,
    summarize_attachment_validation,
)


class BaseEmailMixin(AttachmentMimeTypeMixin):
    """Email-specific functionality mixin."""

    # Default limit for email attachments (in MB)
    email_max_attachment_size_mb: int = 25
    email_geographic_coverage: list[str] | str = ["*"]
    email_geo = email_geographic_coverage

    # Allowed MIME types for email attachments (empty list = all types allowed)
    email_allowed_attachment_mime_types: list[str] = [
        # Documents
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
        "text/plain",
        "text/csv",
        "text/html",
        # Images
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        # Archives
        "application/zip",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/gzip",
    ]

    email_price: float = 0.10
    email_archiving_duration: int = 0  # Days emails remain retrievable
    email_config_fields: list[str] = [
        "email_price",
        "email_archiving_duration",
        "email_max_attachment_size_mb",
        "email_allowed_attachment_mime_types",
    ]
    email_marketing_price: float = 0.12
    email_marketing_archiving_duration: int = 0
    email_marketing_max_attachment_size_mb: int = 25
    email_marketing_allowed_attachment_mime_types: list[str] = list(
        email_allowed_attachment_mime_types
    )
    email_marketing_geographic_coverage: list[str] | str = ["*"]
    email_marketing_geo = email_marketing_geographic_coverage
    email_marketing_config_fields: list[str] = [
        "email_marketing_price",
        "email_marketing_archiving_duration",
        "email_marketing_max_attachment_size_mb",
        "email_marketing_allowed_attachment_mime_types",
    ]

    @property
    def max_email_attachment_size_mb(self) -> int:
        """Backward-compatible accessor for legacy attribute name."""
        return self.email_max_attachment_size_mb

    @property
    def allowed_attachment_mime_types(self) -> list[str]:
        """Backward-compatible accessor for legacy attribute name."""
        return self.email_allowed_attachment_mime_types

    @property
    def max_email_attachment_size_bytes(self) -> int:
        """Return max attachment size in bytes."""
        return int(self.email_max_attachment_size_mb * 1024 * 1024)

    def _get_email_service_value(self, service: str, field: str) -> Any:
        """Return configuration value for a given email service variant."""
        attr_name = f"{service}_{field}"
        if hasattr(self, attr_name):
            value = getattr(self, attr_name)
            if value is not None:
                return value
        if service != "email":
            fallback = f"email_{field}"
            if hasattr(self, fallback):
                return getattr(self, fallback)
        return None

    def _build_email_service_info(self, service: str) -> Dict[str, Any]:
        """Construct a default service information payload."""
        archiving_duration = self._get_email_service_value(
            service, "archiving_duration"
        )
        coverage = self._get_email_service_value(service, "geographic_coverage") or [
            "*"
        ]
        return {
            "credits": None,
            "credits_type": "unlimited",
            "is_available": None,
            "limits": {
                "archiving_duration_days": archiving_duration,
            },
            "warnings": [
                f"get_{service}_service_info() method not implemented for this provider"
            ],
            "reputation": {},
            "details": {
                "geographic_coverage": coverage,
            },
        }

    def get_email_service_info(self) -> Dict[str, Any]:
        """Return email service information. Override in subclasses."""
        return self._build_email_service_info("email")

    def get_email_marketing_service_info(self) -> Dict[str, Any]:
        """Return marketing email service information."""
        return self._build_email_service_info("email_marketing")

    def check_email_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check email delivery status. Override in subclasses."""
        return {
            "status": "unknown",
            "delivered_at": None,
            "opened_at": None,
            "clicked_at": None,
            "opens_count": 0,
            "clicks_count": 0,
            "bounce_type": None,
            "error_code": None,
            "error_message": "check_email_delivery_status() method not implemented for this provider",
            "details": {},
        }

    def check_email_marketing_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check marketing email delivery status."""
        return {
            "status": "unknown",
            "delivered_at": None,
            "opened_at": None,
            "clicked_at": None,
            "opens_count": 0,
            "clicks_count": 0,
            "bounce_type": None,
            "error_code": None,
            "error_message": "check_email_marketing_delivery_status() method not implemented for this provider",
            "details": {},
        }

    def send_email(self, **kwargs) -> bool:
        """Send email. Override in subclasses."""
        recipient_email = self._get_missive_value("get_recipient_email")
        if not recipient_email:
            recipient_email = self._get_missive_value("recipient_email")

        if not recipient_email:
            self._update_status(
                MissiveStatus.FAILED, error_message="No recipient email"
            )
            return False

        raise NotImplementedError(f"{self.name} must implement the send_email() method")

    def send_email_marketing(self, **kwargs) -> bool:
        """Send marketing email. Override in subclasses."""
        raise NotImplementedError(
            f"{self.name} must implement the send_email_marketing() method"
        )

    def validate_email(self, email: str) -> Dict[str, Any]:
        """Validate email and assess delivery risk."""
        warnings: List[str] = []
        details: Dict[str, Any] = {}

        email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        is_valid = bool(re.match(email_regex, email))

        if not is_valid:
            return {
                "is_valid": False,
                "is_deliverable": False,
                "risk_score": 100,
                "warnings": ["Invalid email format"],
                "details": {},
            }

        domain = email.split("@")[1].lower()
        details["domain"] = domain

        risk_score = self._calculate_email_risk_score(email, domain, warnings, details)

        return {
            "is_valid": is_valid,
            "is_deliverable": len(warnings) == 0,
            "risk_score": risk_score,
            "warnings": warnings,
            "details": details,
        }

    def _calculate_email_risk_score(
        self, email: str, domain: str, warnings: List[str], details: Dict[str, Any]
    ) -> int:
        """Calculate email risk score (0-100)."""
        score = 0

        if "Disposable domain detected" in warnings:
            score += 80
        if "No MX record found" in warnings:
            score += 60
        if "SMTP server unreachable" in warnings:
            score += 50

        return min(score, 100)

    def test_smtp_server(self, domain: str) -> Dict[str, Any]:
        """Test SMTP server availability and configuration."""
        return {
            "is_reachable": None,
            "mx_records": [],
            "supports_tls": None,
            "smtp_banner": "",
            "response_time_ms": 0,
            "warnings": ["SMTP diagnostics not implemented"],
        }

    def add_attachment_email(self, attachment: Any) -> Dict[str, Any]:
        """
        Prepare an email attachment for a provider.

        Args:
            attachment: Generic attachment object with optional attributes.

        Returns:
            Provider-agnostic attachment payload.
        """
        file_content: Optional[bytes] = None
        file_obj = getattr(attachment, "file", None)
        if file_obj and hasattr(file_obj, "read"):
            try:
                file_content = file_obj.read()
            except Exception:  # pragma: no cover - defensive
                file_content = None

        return {
            "filename": getattr(attachment, "filename", None),
            "content": file_content,
            "url": getattr(attachment, "external_url", None),
            "mime_type": getattr(attachment, "mime_type", None),
        }

    def check_attachments(self, attachments: List[Any]) -> Dict[str, Any]:
        """
        Validate email attachments against size and MIME type limits.

        Args:
            attachments: List of attachment objects with attributes like:
                - mime_type: MIME type of the file
                - size_bytes: File size in bytes
                - file: File object with read() method (optional)

        Returns:
            Dict with validation results:
                - is_valid: bool
                - errors: List[str] of error messages
                - warnings: List[str] of warning messages
                - details: Dict with per-attachment validation details
        """
        if not attachments:
            return attachment_check_empty_result()

        max_size_bytes = self.max_email_attachment_size_bytes
        return summarize_attachment_validation(
            attachments=attachments,
            mime_checker=lambda attachment, idx: self._check_attachment_mime_type(
                attachment, idx
            ),
            size_checker=lambda attachment, idx: self._check_attachment_size(
                attachment, idx, max_size_bytes
            ),
            max_size_bytes=max_size_bytes,
            max_size_mb=float(self.max_email_attachment_size_mb),
            size_error_template=(
                "Total attachment size ({total_mb:.2f} MB) exceeds maximum of {max_mb:.2f} MB"
            ),
            details_factory=lambda: {
                "total_size_bytes": 0,
                "attachments_checked": 0,
                "attachments_valid": 0,
            },
        )

    def calculate_spam_score(self, subject: str, body: str) -> Dict[str, Any]:
        """Compute a spam score for email content."""
        score = 0
        triggers: List[str] = []
        recommendations: List[str] = []

        # Placeholder for future heuristics/ML integration

        return {
            "spam_score": score,
            "triggers": triggers,
            "recommendations": recommendations,
        }

    def cancel_email(self, **kwargs) -> bool:
        """Cancel a scheduled email (override in subclasses)."""
        return False

    def cancel_email_marketing(self, **kwargs) -> bool:
        """Cancel scheduled marketing email."""
        return False

    def calculate_email_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Calculate delivery risk for email missives."""

        def _handler(
            target_missive: Any,
            factors: Dict[str, Any],
            recommendations: List[str],
            total_risk: float,
        ) -> Dict[str, Any]:
            email = getattr(self, "_get_missive_value", lambda x, d=None: d)(
                "get_recipient_email"
            ) or getattr(target_missive, "recipient_email", None)
            if not email:
                email = getattr(self, "_get_missive_value", lambda x, d=None: d)(
                    "recipient_email"
                )

            if not email:
                recommendations.append("Recipient email missing")
                total_risk_local = 100.0
            else:
                email_validation = self.validate_email(str(email))
                factors["email_validation"] = email_validation
                total_risk_local = total_risk + email_validation.get("risk_score", 0) * 0.6
                recommendations.extend(email_validation.get("warnings", []))

            risk_score = min(int(total_risk_local), 100)
            risk_level = getattr(
                self,
                "_calculate_risk_level",
                lambda x: (
                    "critical"
                    if x >= 75
                    else "high" if x >= 50 else "medium" if x >= 25 else "low"
                ),
            )(risk_score)

            return {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "factors": factors,
                "recommendations": recommendations,
                "should_send": risk_score < 70,
            }

        return self._run_risk_analysis(missive, _handler)

    def calculate_email_marketing_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Calculate delivery risk for marketing emails."""
        return self.calculate_email_delivery_risk(missive)

    def validate_email_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate email webhook signature. Override in subclasses."""
        return True, ""

    def validate_email_marketing_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate marketing email webhook signature."""
        return True, ""

    def handle_email_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process email webhook payload. Override in subclasses."""
        return (
            False,
            "handle_email_webhook() method not implemented for this provider",
            None,
        )

    def handle_email_marketing_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process marketing email webhook payload."""
        return (
            False,
            "handle_email_marketing_webhook() method not implemented for this provider",
            None,
        )

    def extract_email_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extract missive ID from email webhook payload. Override in subclasses."""
        return None

    def extract_email_marketing_missive_id(
        self, payload: Dict[str, Any]
    ) -> Optional[str]:
        """Extract missive ID from marketing email webhook payload."""
        return None

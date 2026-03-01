"""SMS provider mixin without Django dependencies."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ...status import MissiveStatus


class BaseSMSMixin:
    """SMS-specific functionality mixin."""

    sms_price: float = 0.50
    sms_archiving_duration: int = 0  # Days SMS logs stay accessible
    sms_geographic_coverage: list[str] | str = ["*"]
    sms_geo = sms_geographic_coverage
    sms_character_limit: int = 160
    sms_unicode_character_limit: int = 70
    sms_config_fields: list[str] = [
        "sms_price",
        "sms_archiving_duration",
        "sms_character_limit",
        "sms_unicode_character_limit",
    ]

    def get_sms_service_info(self) -> Dict[str, Any]:
        """Return SMS service information. Override in subclasses."""
        return {
            "credits": None,
            "credits_type": "count",
            "is_available": None,
            "limits": {
                "archiving_duration_days": self.sms_archiving_duration,
            },
            "warnings": [
                "get_sms_service_info() method not implemented for this provider"
            ],
            "details": {
                "geographic_coverage": self.sms_geographic_coverage,
            },
        }

    def check_sms_delivery_status(self, **kwargs) -> Dict[str, Any]:
        """Check SMS delivery status. Override in subclasses."""
        return {
            "status": "unknown",
            "delivered_at": None,
            "error_code": None,
            "error_message": "check_sms_delivery_status() method not implemented for this provider",
            "details": {},
        }

    def send_sms(self, **kwargs) -> bool:
        """Send SMS. Override in subclasses."""
        recipient_phone = self._get_missive_value("get_recipient_phone")
        if not recipient_phone:
            recipient_phone = self._get_missive_value("recipient_phone")

        if not recipient_phone:
            self._update_status(MissiveStatus.FAILED, error_message="No phone number")
            return False

        raise NotImplementedError(f"{self.name} must implement the send_sms() method")

    def calculate_sms_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Calculate delivery risk for SMS missives."""

        def _handler(
            _target: Any,
            factors: Dict[str, Any],
            recommendations: List[str],
            total_risk: float,
        ) -> Dict[str, Any]:
            phone = self._get_missive_value("get_recipient_phone")
            if not phone:
                phone = self._get_missive_value("recipient_phone")

            phone_validation: Optional[Dict[str, Any]] = None
            risk_total = total_risk

            if not phone:
                recommendations.append("Recipient phone missing")
                risk_total = 100.0
            else:
                phone_str = str(phone)
                phone_validation = self.validate_phone_number(phone_str)
                factors["phone_validation"] = phone_validation
                risk_total += phone_validation.get("risk_score", 0)
                recommendations.extend(phone_validation.get("warnings", []))

                if not phone_validation.get("is_valid", True):
                    risk_total = max(risk_total, 80)

            risk_score = min(int(risk_total), 100)
            risk_level = self._calculate_risk_level(risk_score)

            phone_is_valid = (
                phone_validation.get("is_valid", True) if phone_validation else False
            )
            should_send = risk_score < 70 and phone_is_valid

            return {
                "risk_score": risk_score,
                "risk_level": risk_level,
                "factors": factors,
                "recommendations": recommendations,
                "should_send": should_send,
            }

        return self._run_risk_analysis(missive, _handler)

    def validate_phone_number(
        self, phone: str, country_code: str = "FR"
    ) -> Dict[str, Any]:
        """Validate a phone number and assess delivery risk."""
        warnings = []
        details: Dict[str, Any] = {}

        cleaned = re.sub(r"[^\d+]", "", phone)
        details["cleaned"] = cleaned

        if not cleaned.startswith("+"):
            warnings.append("International format recommended (+33...)")

        risk_score = len(warnings) * 20

        return {
            "is_valid": len(cleaned) >= 10,
            "is_mobile": None,
            "formatted": cleaned,
            "carrier": "",
            "line_type": "unknown",
            "risk_score": risk_score,
            "warnings": warnings,
        }

    def calculate_sms_segments(self, message: str) -> Dict[str, Any]:
        """Calculate number of SMS segments and estimated cost."""
        gsm7_chars = set(
            "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
            "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
        )

        is_gsm7 = all(c in gsm7_chars for c in message)
        encoding = "GSM-7" if is_gsm7 else "Unicode"

        if is_gsm7:
            single_limit = self.sms_character_limit
            multi_limit = max(self.sms_character_limit - 7, 1)
        else:
            single_limit = self.sms_unicode_character_limit
            multi_limit = max(self.sms_unicode_character_limit - 3, 1)

        length = len(message)
        if length == 0:
            segments = 0
        elif length <= single_limit:
            segments = 1
        else:
            segments = (length + multi_limit - 1) // multi_limit

        cost_per_segment = self._config.get(
            "SMS_COST_PER_SEGMENT", self.sms_price or 0.05
        )
        estimated_cost = segments * cost_per_segment

        return {
            "segments": segments,
            "characters": length,
            "encoding": encoding,
            "estimated_cost": estimated_cost,
            "per_segment_limit": single_limit if segments == 1 else multi_limit,
            "is_multipart": segments > 1,
        }

    def format_phone_international(self, phone: str, country_code: str = "FR") -> str:
        """Format a phone number in international format."""
        cleaned = re.sub(r"[^\d+]", "", phone)

        if cleaned.startswith("+"):
            return cleaned

        if country_code == "FR" and cleaned.startswith("0"):
            return "+33" + cleaned[1:]

        return "+" + cleaned

    def cancel_sms(self, **kwargs) -> bool:
        """Cancel a scheduled SMS (override in subclasses)."""
        return False

    def validate_sms_webhook_signature(
        self, payload: Any, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate SMS webhook signature. Override in subclasses."""
        return True, ""

    def handle_sms_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Any]]:
        """Process SMS webhook payload. Override in subclasses."""
        return (
            False,
            "handle_sms_webhook() method not implemented for this provider",
            None,
        )

    def extract_sms_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extract missive ID from SMS webhook payload. Override in subclasses."""
        return None

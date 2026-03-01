"""Partner providers (SMS, Email, Voice) - Simple implementations."""

import base64
import os
from typing import Any, Dict, Optional

import requests

from .base import MissiveProviderBase


class PartnerProvider(MissiveProviderBase):
    """Abstract base class for Partner providers (SMS, Email, Voice)."""

    abstract = True
    display_name = "Partner"
    description = "French multi-service solution (SMS, Email, Voice)"
    site_url = "https://www.smspartner.fr/"
    documentation_url = "https://www.docpartner.dev/"
    required_packages = ["requests"]

    API_BASE_SMS = "https://api.smspartner.fr/v1"
    API_BASE_VOICE = "https://api.voicepartner.fr/v1"
    API_BASE_EMAIL = "https://api.mailpartner.fr/v1"

    STATUS_MAPPING_SMS = {
        "Delivered": "delivered",
        "Not delivered": "failed",
        "Waiting": "pending",
        "Sent": "sent",
    }

    STATUS_MAPPING_EMAIL = {
        "Delivered": "delivered",
        "Bounced": "bounced",
        "Opened": "opened",
        "Clicked": "clicked",
        "Failed": "failed",
        "Pending": "pending",
    }

    MAX_EMAIL_ATTACHMENTS = 3

    ERROR_CODES = {
        1: "API key required",
        2: "Phone number required",
        3: "Message ID required",
        4: "Message not found",
        5: "Sending already cancelled",
        6: "Cannot cancel less than 5 minutes before sending",
        7: "Cannot cancel already sent message",
        9: "Constraints not met",
        10: "Incorrect API key",
        11: "Low credits",
    }

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        if not hasattr(self, "attachments"):
            self.attachments = []

    def _get_api_key(self) -> Optional[str]:
        """Return the API key."""
        return self._get_config_or_env("API_KEY")

    def _perform_request(
        self,
        method: str,
        url: str,
        *,
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ):
        """Perform an HTTP request."""
        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        if json_payload is not None:
            request_kwargs["json"] = json_payload
        if params:
            request_kwargs["params"] = params
        if headers:
            request_kwargs["headers"] = headers

        http_callable = getattr(requests, method)
        return http_callable(url, **request_kwargs)

    def _safe_json(self, response: Any) -> Dict[str, Any]:
        """Parse JSON safely."""
        try:
            json_data = response.json()
            if isinstance(json_data, dict):
                return json_data
            return {}
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON response: {exc}") from exc

    def _get_message_text(self, **kwargs: Any) -> str:
        """Return the message text."""
        body_text = kwargs.get("body_text")
        if body_text:
            return str(body_text)
        body = kwargs.get("body")
        return str(body) if body else ""

    def _get_error_message(self, code: Optional[int], default: str = "") -> str:
        """Return the error message corresponding to the code."""
        if code is None:
            return default or "Unknown error"
        return self.ERROR_CODES.get(code, default or f"Error {code}")

    def _update_missive_event(
        self,
        status: str,
        error_message: str | None = None,
        external_id: str | None = None,
        provider: str | None = None,
    ) -> None:
        """Update the missive status."""
        if self.missive:
            if hasattr(self.missive, "status"):
                self.missive.status = status
            if error_message and hasattr(self.missive, "error_message"):
                self.missive.error_message = error_message
            if external_id and hasattr(self.missive, "external_id"):
                self.missive.external_id = external_id
            if provider and hasattr(self.missive, "provider"):
                self.missive.provider = provider
            elif hasattr(self.missive, "provider"):
                self.missive.provider = self.name
            if hasattr(self.missive, "save"):
                self.missive.save()

    def add_attachment_email(self, content: bytes | str, name: str) -> None:
        """Add an attachment to the email."""
        if not hasattr(self, "attachments"):
            self.attachments = []

        if isinstance(content, str):
            content = content.encode("utf-8")

        self.attachments.append({"content": content, "name": os.path.basename(name)})

    def remove_attachment_email(self, name: str) -> None:
        """Remove an attachment from the email."""
        if not hasattr(self, "attachments"):
            return

        self.attachments = [att for att in self.attachments if att["name"] != name]


class SmsPartnerProvider(PartnerProvider):
    """SMS Partner provider specialized for SMS."""

    name = "sms_partner"
    display_name = "SMS Partner"
    supported_types = ["SMS"]
    services = ["sms", "sms_low_cost", "sms_premium"]
    config_keys = ["API_KEY", "SENDER"]
    config_defaults = {
        "SENDER": "Missive",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize SMS Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_SMS

    def prepare_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Prepare SMS payload."""
        phone = kwargs.get("recipient_phone")
        if not phone:
            raise ValueError("recipient_phone is required")

        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("API_KEY is required")

        message = self._get_message_text(**kwargs)
        if not message:
            raise ValueError("Message text is required")

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "phoneNumbers": phone,
            "message": message,
            "sender": self._get_config_or_env("SENDER", "Missive"),
            "gamme": 1,
        }

        return payload

    def send_sms(self, **kwargs: Any) -> bool:
        """Send an SMS via SMSPartner."""
        try:
            payload = self.prepare_sms(**kwargs)

            response = self._perform_request(
                "post",
                f"{self._api_base}/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:
            self._update_missive_event("FAILED", error_message=str(exc))
            return False

        if result.get("success") is True:
            message_id = result.get("message_id") or result.get("messageId")
            self._update_missive_event(
                "SENT",
                external_id=str(message_id) if message_id else None,
                provider=self.name,
            )
            return True

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        self._update_missive_event("FAILED", error_message=error_msg)
        return False

    def cancel_sms(self, **kwargs: Any) -> bool:
        """Cancel an SMS."""
        external_id = kwargs.get("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "delete",
                f"{self._api_base}/message-cancel/{external_id}",
                params={"apiKey": api_key},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:
            return False

        return result.get("success") is True

    def status_sms(self, **kwargs: Any) -> Dict[str, Any]:
        """Check SMS delivery status."""
        external_id = kwargs.get("external_id")
        phone = kwargs.get("recipient_phone")
        if not external_id or not phone:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "Missing external_id or recipient_phone",
                "details": {},
            }

        api_key = self._get_api_key()
        if not api_key:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "API_KEY missing",
                "details": {},
            }

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/message-status",
                params={
                    "apiKey": api_key,
                    "phoneNumber": phone,
                    "messageId": external_id,
                },
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": str(exc),
                "details": {},
            }

        if result.get("success") is True:
            status_label = result.get("statut", "Unknown")
            status = self.STATUS_MAPPING_SMS.get(status_label, "unknown")
            return {
                "status": status,
                "delivered_at": result.get("date"),
                "error_code": None,
                "error_message": None,
                "details": {
                    "original_status": status_label,
                    "cost": result.get("cost"),
                    "currency": result.get("currency", "EUR"),
                },
            }

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        return {
            "status": "unknown",
            "delivered_at": None,
            "error_code": code,
            "error_message": error_msg,
            "details": result,
        }


class EmailPartnerProvider(PartnerProvider):
    """Email Partner provider specialized for emails."""

    name = "email_partner"
    display_name = "Email Partner"
    supported_types = ["EMAIL"]
    services = ["email"]
    config_keys = ["API_KEY", "FROM_EMAIL", "FROM_NAME"]
    config_defaults = {
        "FROM_EMAIL": "noreply@example.com",
        "FROM_NAME": "",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Email Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_EMAIL

    def prepare_email(self, **kwargs: Any) -> Dict[str, Any]:
        """Prepare email payload."""
        email = kwargs.get("recipient_email")
        if not email:
            raise ValueError("recipient_email is required")

        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("API_KEY is required")

        from_email = self._get_config_or_env("FROM_EMAIL", "noreply@example.com")
        from_name = self._get_config_or_env("FROM_NAME", "")

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "subject": kwargs.get("subject", ""),
            "htmlContent": self._get_message_text(**kwargs),
            "from": {"email": from_email, "name": from_name},
            "to": [{"email": email}],
        }

        if self.attachments:
            payload["attachments"] = [
                {
                    "base64Content": base64.b64encode(att["content"]).decode("utf-8")
                    if isinstance(att["content"], bytes)
                    else att["content"],
                    "contentType": "application/octet-stream",
                    "filename": att["name"],
                }
                for att in self.attachments[: self.MAX_EMAIL_ATTACHMENTS]
            ]

        return payload

    def send_email(self, **kwargs: Any) -> bool:
        """Send an email via MailPartner."""
        try:
            payload = self.prepare_email(**kwargs)

            response = self._perform_request(
                "post",
                f"{self._api_base}/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:
            self._update_missive_event("FAILED", error_message=str(exc))
            return False

        if result.get("success") is True:
            message_id = result.get("messageId") or result.get("message_id")
            self._update_missive_event(
                "SENT",
                external_id=str(message_id) if message_id else None,
                provider=self.name,
            )
            return True

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        self._update_missive_event("FAILED", error_message=error_msg)
        return False

    def cancel_email(self, **kwargs: Any) -> bool:
        """Cancel an email."""
        external_id = kwargs.get("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/message-cancel",
                params={"apiKey": api_key, "messageId": external_id},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:
            return False

        return result.get("success") is True

    def status_email(self, **kwargs: Any) -> Dict[str, Any]:
        """Check email delivery status."""
        external_id = kwargs.get("external_id")
        if not external_id:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "Missing external_id",
                "details": {},
            }

        api_key = self._get_api_key()
        if not api_key:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "API_KEY missing",
                "details": {},
            }

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/bulk-status",
                params={"apiKey": api_key, "messageId": external_id},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": str(exc),
                "details": {},
            }

        if result.get("success") is True:
            status_list = result.get("StatutResponseList", [])
            status_entry = status_list[0] if status_list else {}
            status_label = status_entry.get("statut", "Unknown")
            status = self.STATUS_MAPPING_EMAIL.get(status_label, "unknown")
            return {
                "status": status,
                "delivered_at": status_entry.get("date"),
                "error_code": None,
                "error_message": None,
                "details": {
                    "original_status": status_label,
                    "cost": status_entry.get("cost"),
                    "currency": status_entry.get("currency", "EUR"),
                },
            }

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        return {
            "status": "unknown",
            "delivered_at": None,
            "error_code": code,
            "error_message": error_msg,
            "details": result,
        }


class VoiceCallPartnerProvider(PartnerProvider):
    """Voice Call Partner provider specialized for voice calls."""

    name = "voice_call_partner"
    display_name = "Voice Call Partner"
    supported_types = ["VOICE_CALL"]
    services = ["voice_message", "voice_call"]
    config_keys = ["API_KEY"]

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Voice Call Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_VOICE

    def prepare_voice_call(self, **kwargs: Any) -> Dict[str, Any]:
        """Prepare voice call payload."""
        phone = kwargs.get("recipient_phone")
        if not phone:
            raise ValueError("recipient_phone is required")

        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("API_KEY is required")

        message = self._get_message_text(**kwargs)
        if not message:
            raise ValueError("Message text is required")

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "phoneNumbers": phone,
            "text": message,
            "lang": "fr",
        }

        return payload

    def send_voice_call(self, **kwargs: Any) -> bool:
        """Send a voice call via VoicePartner."""
        try:
            payload = self.prepare_voice_call(**kwargs)

            response = self._perform_request(
                "post",
                f"{self._api_base}/tts/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:
            self._update_missive_event("FAILED", error_message=str(exc))
            return False

        if result.get("success") is True:
            campaign_id = result.get("campaignId")
            self._update_missive_event(
                "SENT",
                external_id=str(campaign_id) if campaign_id else None,
                provider=self.name,
            )
            return True

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        self._update_missive_event("FAILED", error_message=error_msg)
        return False

    def cancel_voice_call(self, **kwargs: Any) -> bool:
        """Cancel a voice call."""
        external_id = kwargs.get("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "delete",
                f"{self._api_base}/campaign/cancel/{api_key}/{external_id}",
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:
            return False

        return result.get("success") is True

    def status_voice_call(self, **kwargs: Any) -> Dict[str, Any]:
        """Check voice call delivery status."""
        external_id = kwargs.get("external_id")
        if not external_id:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "Missing external_id",
                "details": {},
            }

        api_key = self._get_api_key()
        if not api_key:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": "API_KEY missing",
                "details": {},
            }

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/campaign/{api_key}/{external_id}",
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:
            return {
                "status": "unknown",
                "delivered_at": None,
                "error_code": None,
                "error_message": str(exc),
                "details": {},
            }

        if result.get("success") is True:
            status_label = result.get("status", "Unknown")
            status = status_label.lower()
            return {
                "status": status,
                "delivered_at": result.get("endDate"),
                "error_code": None,
                "error_message": None,
                "details": result,
            }

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        return {
            "status": "unknown",
            "delivered_at": None,
            "error_code": code,
            "error_message": error_msg,
            "details": result,
        }

"""Partner providers (SMS, Email, Voice) - Base and specialized implementations."""

import ipaddress
import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

from .base import MissiveProviderBase


class PartnerProvider(MissiveProviderBase):
    """Classe de base abstraite pour les providers Partner (SMS, Email, Voice)."""

    abstract = True
    display_name = "Partner"
    description = "French multi-service solution (SMS, Email, Voice)"
    site_url = "https://www.smspartner.fr/"
    status_url = "https://status.smspartner.fr/status/nda-media"
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
    MAX_EMAIL_VARIABLES = 8

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

    def __init__(
        self,
        *args: Any,
        http_get: Optional[Callable[..., Any]] = None,
        http_post: Optional[Callable[..., Any]] = None,
        http_delete: Optional[Callable[..., Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._http_overrides: Dict[str, Optional[Callable[..., Any]]] = {
            "get": http_get,
            "post": http_post,
            "delete": http_delete,
        }

    def _get_api_key(self) -> Optional[str]:
        """Retourne la clé API."""
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
        """Effectue une requête HTTP."""
        http_callable = self._http_overrides.get(method)
        if http_callable is None:
            http_callable = getattr(requests, method)

        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        if json_payload is not None:
            request_kwargs["json"] = json_payload
        if params:
            request_kwargs["params"] = params
        if headers:
            request_kwargs["headers"] = headers

        try:
            return http_callable(url, **request_kwargs)
        except TypeError:
            if params:
                url = f"{url}?{urlencode(params)}"
                request_kwargs.pop("params", None)
            if headers:
                request_kwargs.pop("headers", None)
            return http_callable(url, **request_kwargs)

    def _safe_json(self, response: Any) -> Dict[str, Any]:
        """Parse JSON de manière sécurisée."""
        try:
            json_data = response.json()
            if isinstance(json_data, dict):
                return json_data
            return {}
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON response: {exc}") from exc

    def _merge_options(self, **kwargs: Any) -> Dict[str, Any]:
        """Fusionne les options du provider avec les kwargs."""
        options: Dict[str, Any] = {}
        provider_options = self._get_missive_value("provider_options", {})
        if isinstance(provider_options, dict):
            options.update(provider_options)
        options.update(kwargs)
        return options

    def _get_message_text(self) -> str:
        """Retourne le texte du message."""
        body_text = self._get_missive_value("body_text")
        if body_text:
            return str(body_text)
        body = self._get_missive_value("body")
        return str(body) if body else ""

    def _build_delivery_status_error(
        self,
        error_msg: str,
        *,
        include_email_fields: bool = False,
    ) -> Dict[str, Any]:
        """Construit une réponse d'erreur pour le statut de livraison."""
        payload: Dict[str, Any] = {
            "status": "unknown",
            "delivered_at": None,
            "error_code": None,
            "error_message": error_msg,
            "details": {},
        }
        if include_email_fields:
            payload.update(
                {
                    "opened_at": None,
                    "clicked_at": None,
                    "opens_count": 0,
                    "clicks_count": 0,
                    "bounce_type": None,
                }
            )
        return payload

    def _get_error_message(self, code: Optional[int], default: str = "") -> str:
        """Retourne le message d'erreur correspondant au code."""
        if code is None:
            return default or "Unknown error"
        return self.ERROR_CODES.get(code, default or f"Error {code}")

    def _to_iso(self, timestamp: Any) -> Optional[str]:
        """Convertit un timestamp en ISO."""
        if timestamp in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(int(timestamp)).isoformat()
        except (ValueError, TypeError):
            return str(timestamp)

    def _format_sms_errors(self, result: Dict[str, Any]) -> str:
        """Formate les erreurs de l'API."""
        errors = result.get("errors", [])
        if errors:
            return "; ".join(err.get("message", "") for err in errors)
        code = result.get("code")
        message = result.get("message", "")
        return self._get_error_message(code, message)

    def validate_webhook_signature(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Valide la signature d'un webhook."""
        allowed_ips = self._get_config_or_env("WEBHOOK_IPS")
        if not allowed_ips:
            return True, ""

        client_ip = headers.get("X-Forwarded-For") or headers.get("X-Real-IP")
        if not client_ip:
            return False, "Missing client IP header"

        try:
            network = ipaddress.ip_network(str(allowed_ips), strict=False)
            if ipaddress.ip_address(client_ip) not in network:
                return False, f"IP {client_ip} not allowed"
        except ValueError:
            allowed_list = [ip.strip() for ip in str(allowed_ips).split(",")]
            if client_ip not in allowed_list:
                return False, f"IP {client_ip} not allowed"

        return True, ""

    def extract_event_type(self, payload: Dict[str, Any]) -> str:
        """Extrait le type d'événement depuis le payload."""
        result = payload.get("status") or payload.get("event", "unknown")
        return str(result)


class SmsPartnerProvider(PartnerProvider):
    """Provider SMS Partner spécialisé pour les SMS."""

    name = "sms_partner"
    display_name = "SMS Partner"
    supported_types = ["SMS"]
    services = ["sms", "sms_low_cost", "sms_premium"]
    config_keys = ["API_KEY", "SENDER", "WEBHOOK_IPS", "WEBHOOK_URL"]
    config_defaults = {
        "SENDER": "Missive",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize SMS Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_SMS

    def send_sms(self, **kwargs: Any) -> bool:
        """Envoie un SMS via SMSPartner."""
        phone = self._get_missive_value("recipient_phone")
        if not phone:
            self._update_status("FAILED", error_message="Phone missing")
            return False

        api_key = self._get_api_key()
        if not api_key:
            self._update_status("FAILED", error_message="API_KEY missing")
            return False

        message = self._get_message_text()
        options = self._merge_options(**kwargs)

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "phoneNumbers": phone,
            "message": message,
            "sender": options.get("sender", self._get_config_or_env("SENDER", "Missive")),
            "gamme": 1,
        }

        tag = options.get("tag") or f"missive_{self._get_missive_value('id', 'unknown')}"
        payload["tag"] = tag

        webhook_url = options.get("webhook_url") or self._get_config_or_env("WEBHOOK_URL")
        if webhook_url:
            payload["webhookUrl"] = webhook_url
            payload["urlDlr"] = webhook_url
            payload["urlResponse"] = webhook_url

        priority_map = {"low": 2, "normal": 1, "high": 3}
        if "priority" in options:
            payload["gamme"] = priority_map.get(options["priority"], 1)
        if options.get("is_commercial") is not None:
            payload["isStopSms"] = 1 if options["is_commercial"] else 0
        if options.get("is_unicode") is not None:
            payload["isUnicode"] = 1 if options["is_unicode"] else 0
        if options.get("sandbox") is not None:
            payload["sandbox"] = 1 if options["sandbox"] else 0

        if options.get("scheduled_delivery_date"):
            payload["scheduledDeliveryDate"] = options["scheduled_delivery_date"]
            payload["time"] = options.get("scheduled_time", 12)
            payload["minute"] = options.get("scheduled_minute", 0)

        if options.get("_format"):
            payload["_format"] = options["_format"]

        try:
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
            message = f"Error calling SMSPartner API: {exc}"
            self._update_status("FAILED", error_message=message)
            return False

        if result.get("success") is True:
            message_id = result.get("message_id") or result.get("messageId")
            self._update_status(
                "SENT",
                provider=self.name,
                external_id=str(message_id) if message_id else None,
            )
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status("FAILED", error_message=error_msg)
        return False

    def cancel_sms(self, **kwargs: Any) -> bool:
        """Annule un SMS."""
        external_id = self._get_missive_value("external_id")
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

    def check_sms_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        """Vérifie le statut de livraison d'un SMS."""
        external_id = self._get_missive_value("external_id")
        phone = self._get_missive_value("recipient_phone")
        if not external_id:
            return self._build_delivery_status_error("Missing external_id")
        if not phone:
            return self._build_delivery_status_error("Recipient phone missing")

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error("API_KEY missing")

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
            return self._build_delivery_status_error(str(exc))

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
                    "country_code": result.get("countryCode"),
                    "stop_sms": result.get("stopSms", False),
                    "number": result.get("number"),
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

    def handle_sms_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Traite un webhook SMS."""
        message_id = self.extract_sms_missive_id(payload)
        if not message_id:
            return False, "message_id missing", None

        event = payload.get("status", "unknown").lower()
        normalized = {
            "message_id": message_id,
            "event": event,
            "delivered_at": payload.get("date"),
            "raw": payload,
        }
        return True, "", normalized

    def extract_sms_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extrait l'ID de la missive depuis le webhook SMS."""
        result = (
            payload.get("message_id")
            or payload.get("messageId")
            or payload.get("tag", "").replace("missive_", "")
        )
        return str(result) if result else None


class EmailPartnerProvider(PartnerProvider):
    """Provider Email Partner spécialisé pour les emails."""

    name = "email_partner"
    display_name = "Email Partner"
    supported_types = ["EMAIL"]
    services = ["email"]
    config_keys = ["API_KEY", "FROM_EMAIL", "FROM_NAME", "WEBHOOK_IPS", "WEBHOOK_URL"]
    config_defaults = {
        "FROM_EMAIL": "noreply@example.com",
        "FROM_NAME": "",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Email Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_EMAIL

    def send_email(self, **kwargs: Any) -> bool:
        """Envoie un email via MailPartner."""
        email = self._get_missive_value("recipient_email")
        if not email:
            self._update_status("FAILED", error_message="Email missing")
            return False

        api_key = self._get_api_key()
        if not api_key:
            self._update_status("FAILED", error_message="API_KEY missing")
            return False

        options = self._merge_options(**kwargs)
        from_email = self._get_config_or_env("FROM_EMAIL", "noreply@example.com")
        from_name = self._get_config_or_env("FROM_NAME", "")

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "subject": self._get_missive_value("subject", ""),
            "htmlContent": self._get_message_text(),
            "from": {"email": from_email, "name": from_name},
            "to": [{"email": email}],
        }

        reply_to = options.get("reply_to")
        if reply_to:
            payload["replyTo"] = (
                {"email": reply_to} if isinstance(reply_to, str) else reply_to
            )

        variables = options.get("template_vars") or options.get("variables")
        if isinstance(variables, dict) and len(variables) <= self.MAX_EMAIL_VARIABLES:
            payload["variables"] = variables

        tag = options.get("tag")
        if isinstance(tag, str):
            payload["tag"] = tag[:20].lower().replace(" ", "")

        attachments = options.get("attachments")
        if isinstance(attachments, list):
            payload["attachments"] = [
                {
                    "base64Content": att.get("base64Content"),
                    "contentType": att.get("contentType", "application/octet-stream"),
                    "filename": att.get("filename", "file"),
                }
                for att in attachments[: self.MAX_EMAIL_ATTACHMENTS]
                if att.get("base64Content")
            ]

        if options.get("scheduled_delivery_date"):
            payload["scheduledDeliveryDate"] = options["scheduled_delivery_date"]
            payload["time"] = options.get("scheduled_time", 12)
            payload["minute"] = options.get("scheduled_minute", 0)

        if options.get("sandbox"):
            payload["sandbox"] = 1

        try:
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
            message = f"Error calling Mail Partner API: {exc}"
            self._update_status("FAILED", error_message=message)
            return False

        if result.get("success") is True:
            message_id = result.get("messageId") or result.get("message_id")
            self._update_status(
                "SENT",
                provider=self.name,
                external_id=str(message_id) if message_id else None,
            )
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status("FAILED", error_message=error_msg)
        return False

    def cancel_email(self, **kwargs: Any) -> bool:
        """Annule un email."""
        external_id = self._get_missive_value("external_id")
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

    def check_email_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        """Vérifie le statut de livraison d'un email."""
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return self._build_delivery_status_error(
                "Missing external_id", include_email_fields=True
            )

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error(
                "API_KEY missing", include_email_fields=True
            )

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/bulk-status",
                params={"apiKey": api_key, "messageId": external_id},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:
            return self._build_delivery_status_error(
                str(exc), include_email_fields=True
            )

        if result.get("success") is True:
            status_list = result.get("StatutResponseList", [])
            status_entry = status_list[0] if status_list else {}
            status_label = status_entry.get("statut", "Unknown")
            status = self.STATUS_MAPPING_EMAIL.get(status_label, "unknown")
            return {
                "status": status,
                "delivered_at": status_entry.get("date"),
                "opened_at": None,
                "clicked_at": None,
                "opens_count": status_entry.get("open", 0),
                "clicks_count": status_entry.get("click", 0),
                "bounce_type": status_entry.get("bounceType"),
                "error_code": None,
                "error_message": None,
                "details": {
                    "original_status": status_label,
                    "cost": status_entry.get("cost"),
                    "currency": status_entry.get("currency", "EUR"),
                    "stop_mail": status_entry.get("stopMail"),
                    "email": status_entry.get("email"),
                },
            }

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        return self._build_delivery_status_error(error_msg, include_email_fields=True)

    def handle_email_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Traite un webhook email."""
        message_id = self.extract_email_missive_id(payload)
        if not message_id:
            return False, "message_id missing", None
        normalized = {
            "message_id": message_id,
            "event": payload.get("event", "unknown").lower(),
            "raw": payload,
        }
        return True, "", normalized

    def extract_email_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extrait l'ID de la missive depuis le webhook email."""
        tag = payload.get("tag", "")
        if tag and isinstance(tag, str) and tag.startswith("missive_"):
            return tag.replace("missive_", "")
        result = payload.get("messageId") or payload.get("message_id")
        if result and isinstance(result, (str, int)):
            return str(result)
        return None


class VoiceCallPartnerProvider(PartnerProvider):
    """Provider Voice Call Partner spécialisé pour les appels vocaux."""

    name = "voice_call_partner"
    display_name = "Voice Call Partner"
    supported_types = ["VOICE_CALL"]
    services = ["voice_message", "voice_call"]
    config_keys = ["API_KEY", "WEBHOOK_IPS", "WEBHOOK_URL"]

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Voice Call Partner provider."""
        super().__init__(**kwargs)
        self._api_base = self.API_BASE_VOICE

    def send_voice_call(self, **kwargs: Any) -> bool:
        """Envoie un appel vocal via VoicePartner."""
        phone = self._get_missive_value("recipient_phone")
        api_key = self._get_api_key()
        if not phone or not api_key:
            self._update_status(
                "FAILED",
                error_message="Phone missing or API_KEY missing",
            )
            return False

        options = self._merge_options(**kwargs)
        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "phoneNumbers": phone,
            "lang": options.get("lang", "fr"),
        }

        if options.get("token_audio"):
            payload["tokenAudio"] = options["token_audio"]
        else:
            payload["text"] = self._get_message_text()

        if options.get("speech_rate"):
            payload["speechRate"] = options["speech_rate"]
        if options.get("notify_url") or options.get("webhook_url"):
            payload["notifyUrl"] = options.get("notify_url") or options.get(
                "webhook_url"
            )
        if options.get("scheduled_date") or options.get("scheduled_delivery_date"):
            payload["scheduledDate"] = options.get("scheduled_date") or options.get(
                "scheduled_delivery_date"
            )

        try:
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
            message = f"Error calling Voice Partner API: {exc}"
            self._update_status("FAILED", error_message=message)
            return False

        if result.get("success") is True:
            campaign_id = result.get("campaignId")
            self._update_status(
                "SENT",
                provider=self.name,
                external_id=str(campaign_id) if campaign_id else None,
            )
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status("FAILED", error_message=error_msg)
        return False

    def cancel_voice_call(self, **kwargs: Any) -> bool:
        """Annule un appel vocal."""
        external_id = self._get_missive_value("external_id")
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

    def check_voice_call_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        """Vérifie le statut de livraison d'un appel vocal."""
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return self._build_delivery_status_error("Missing external_id")

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error("API_KEY missing")

        try:
            response = self._perform_request(
                "get",
                f"{self._api_base}/campaign/{api_key}/{external_id}",
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:
            return self._build_delivery_status_error(str(exc))

        if result.get("success") is True:
            status_label = result.get("status", "Unknown")
            status = status_label.lower()
            return {
                "status": status,
                "delivered_at": self._to_iso(result.get("endDate")),
                "error_code": None,
                "error_message": None,
                "details": result,
            }

        code = result.get("code")
        message = result.get("message", "")
        error_msg = self._get_error_message(code, message)
        return self._build_delivery_status_error(error_msg)

    def handle_voice_call_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Traite un webhook voice call."""
        campaign_id = payload.get("campaignId") or payload.get("campaign_id")
        if not campaign_id:
            return False, "campaignId missing", None
        normalized = {
            "message_id": str(campaign_id),
            "event": payload.get("status", "unknown").lower(),
            "raw": payload,
        }
        return True, "", normalized

    def extract_voice_call_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extrait l'ID de la missive depuis le webhook voice call."""
        return payload.get("campaignId") or payload.get("campaign_id")

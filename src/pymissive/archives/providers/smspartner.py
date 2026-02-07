"""High-level SMSPartner provider without Django dependencies."""

from __future__ import annotations

import ipaddress
import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

from ..status import MissiveStatus
from .base import BaseProvider

HttpCallable = Callable[..., Any]


class SMSPartnerProvider(BaseProvider):
    """SMSPartner implementation covering SMS, Email and Voice services."""

    name = "SMS Partner"
    display_name = "SMS Partner (SMS/Email/Voice)"
    supported_types = ["SMS", "EMAIL", "VOICE_CALL"]
    services = [
        "sms",
        "sms_low_cost",
        "sms_premium",
        "voice_message",
        "voice_call",
        "email",
    ]
    # Geographic scopes
    sms_geo = "*"
    email_geo = "*"
    voice_call_geo = "*"
    config_keys = [
        "SMSPARTNER_API_KEY",
        "SMSPARTNER_SENDER",
        "SMSPARTNER_WEBHOOK_IPS",
        "SMSPARTNER_WEBHOOK_URL",
        "DEFAULT_FROM_EMAIL",
        "DEFAULT_FROM_NAME",
    ]
    required_packages = ["requests"]
    site_url = "https://www.smspartner.fr/"
    status_url = "https://status.smspartner.fr/status/nda-media"
    documentation_url = "https://www.docpartner.dev/"
    description_text = "French multi-service solution (SMS, Email, Voice)"

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

    WARNING_THRESHOLD_SMS = 500
    CRITICAL_THRESHOLD_SMS = 100
    WARNING_THRESHOLD_BALANCE = 10.0
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
        http_get: Optional[HttpCallable] = None,
        http_post: Optional[HttpCallable] = None,
        http_delete: Optional[HttpCallable] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._http_overrides: Dict[str, Optional[HttpCallable]] = {
            "get": http_get,
            "post": http_post,
            "delete": http_delete,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_api_key(self) -> Optional[str]:
        return self._config.get("SMSPARTNER_API_KEY")

    def _get_requests(self):
        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError("requests package required") from exc
        return requests

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
        http_callable = self._http_overrides.get(method)
        if http_callable is None:
            requests = self._get_requests()
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
            # Tests inject simple callables that may not accept extra kwargs.
            if params:
                url = f"{url}?{urlencode(params)}"
                request_kwargs.pop("params", None)
            if headers:
                request_kwargs.pop("headers", None)
            return http_callable(url, **request_kwargs)

    def _safe_json(self, response: Any) -> Dict[str, Any]:
        try:
            json_data = response.json()
            if isinstance(json_data, dict):
                return json_data
            return {}  # Return empty dict if not a dict
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Invalid JSON response: {exc}") from exc

    def _merge_options(self, **kwargs: Any) -> Dict[str, Any]:
        options: Dict[str, Any] = {}
        provider_options = self._get_missive_value("provider_options", {})
        if isinstance(provider_options, dict):
            options.update(provider_options)
        options.update(kwargs)
        return options

    def _get_message_text(self) -> str:
        body_text = self._get_missive_value("body_text")
        if body_text:
            return str(body_text)
        body = self._get_missive_value("body")
        return str(body) if body else ""

    def _fail_from_risk(self, risk: Dict[str, Any], fallback_msg: str) -> None:
        message = next(
            (rec for rec in risk.get("recommendations", []) if rec), fallback_msg
        )
        self._update_status(MissiveStatus.FAILED, error_message=message)
        self._create_event("failed", message)

    def _build_error_response(
        self,
        error_msg: str,
        *,
        credits_type: str = "count",
        is_available: Optional[bool] = False,
    ) -> Dict[str, Any]:
        return {
            "credits": None,
            "credits_type": credits_type,
            "is_available": is_available,
            "limits": {},
            "warnings": [error_msg],
            "details": {},
        }

    def _build_delivery_status_error(
        self,
        error_msg: str,
        *,
        include_email_fields: bool = False,
    ) -> Dict[str, Any]:
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
        if code is None:
            return default or "Unknown error"
        return self.ERROR_CODES.get(code, default or f"Error {code}")

    def _to_iso(self, timestamp: Any) -> Optional[str]:
        if timestamp in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(int(timestamp)).isoformat()
        except (ValueError, TypeError):
            return str(timestamp)

    # ------------------------------------------------------------------
    # Risk calculations
    # ------------------------------------------------------------------

    def calculate_sms_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        base_risk: Dict[str, Any] = super().calculate_sms_delivery_risk(missive)
        if not base_risk.get("should_send", True):
            return base_risk

        recommendations = list(base_risk.get("recommendations", []))
        risk_score = float(base_risk.get("risk_score", 0))

        if not self._get_api_key():
            recommendations.append("SMSPARTNER_API_KEY not configured")
            return {
                **base_risk,
                "risk_score": 100,
                "risk_level": "critical",
                "recommendations": recommendations,
                "should_send": False,
            }

        message = self._get_message_text()
        if not message:
            recommendations.append("Message body is empty")
            return {
                **base_risk,
                "risk_score": 100,
                "risk_level": "critical",
                "recommendations": recommendations,
                "should_send": False,
            }

        base_risk["recommendations"] = recommendations
        base_risk["risk_score"] = int(risk_score)
        return base_risk

    def calculate_email_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        # Call the instance method from BaseEmailMixin
        base_risk: Dict[str, Any] = super().calculate_email_delivery_risk(missive)
        if not base_risk.get("should_send", True):
            return base_risk

        recommendations = list(base_risk.get("recommendations", []))
        risk_score = float(base_risk.get("risk_score", 0))

        if not self._get_api_key():
            recommendations.append("SMSPARTNER_API_KEY not configured")
            return {
                **base_risk,
                "risk_score": 100,
                "risk_level": "critical",
                "recommendations": recommendations,
                "should_send": False,
            }

        subject = self._get_missive_value("subject")
        if not subject:
            recommendations.append("Email subject missing")
            risk_score = max(risk_score, 40)

        base_risk["risk_score"] = int(risk_score)
        base_risk["recommendations"] = recommendations
        return base_risk

    def calculate_voice_call_delivery_risk(
        self, missive: Optional[Any] = None
    ) -> Dict[str, Any]:
        _target, fallback, *_ = self._start_risk_analysis(missive)
        if fallback is not None or _target is None:
            return fallback or self._risk_missing_missive_payload()

        phone = self._get_missive_value("recipient_phone")
        if not phone:
            return {
                **self._risk_missing_missive_payload(),
                "recommendations": ["Recipient phone missing"],
            }

        if not self._get_api_key():
            return {
                **self._risk_missing_missive_payload(),
                "recommendations": ["SMSPARTNER_API_KEY not configured"],
            }

        return {
            "risk_score": 20,
            "risk_level": "low",
            "factors": {"phone": phone},
            "recommendations": [],
            "should_send": True,
        }

    # ------------------------------------------------------------------
    # Service information
    # ------------------------------------------------------------------

    def get_sms_service_info(self) -> Dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return self._build_error_response("SMSPARTNER_API_KEY missing")

        try:
            response = self._perform_request(
                "get", f"{self.API_BASE_SMS}/me", params={"apiKey": api_key}, timeout=5
            )
        except Exception as exc:  # pragma: no cover - network layer
            return self._build_error_response(f"Error connecting to API: {exc}")

        if getattr(response, "status_code", None) == 429:
            return self._build_error_response("Rate limit exceeded")
        if getattr(response, "status_code", None) != 200:
            return self._build_error_response(
                f"HTTP error {getattr(response, 'status_code', 'unknown')}"
            )

        payload = self._safe_json(response)
        if payload.get("success") is not True:
            code = payload.get("code", "unknown")
            return self._build_error_response(f"API error (code {code})")

        credits = payload.get("credits", {})
        credit_sms = int(credits.get("creditSms", 0))
        credit_sms_eco = int(credits.get("creditSmsECO", 0))
        total_sms = credit_sms + credit_sms_eco
        solde_eur = float(credits.get("solde", 0))

        warnings = []
        if total_sms < self.CRITICAL_THRESHOLD_SMS:
            warnings.append(f"Critical SMS credits: {total_sms} messages remaining")
        elif total_sms < self.WARNING_THRESHOLD_SMS:
            warnings.append(f"Low SMS credits: {total_sms} messages remaining")
        if solde_eur < self.WARNING_THRESHOLD_BALANCE:
            warnings.append(f"Critical balance: {solde_eur:.2f}€")

        return {
            "credits": f"{total_sms} SMS (Classique: {credit_sms}, ECO: {credit_sms_eco})",
            "credits_type": "count",
            "is_available": total_sms > 0,
            "limits": {"per_second": 5, "per_minute": 300},
            "warnings": warnings,
            "details": {
                "credit_sms_classique": credit_sms,
                "credit_sms_eco": credit_sms_eco,
                "credit_hlr": int(credits.get("creditHlr", 0)),
                "solde_eur": solde_eur,
                "currency": credits.get("currency", "EUR"),
                "to_send": int(credits.get("toSend", 0)),
                "sender": self._config.get("SMSPARTNER_SENDER", "undefined"),
                "user_info": payload.get("user", {}),
            },
        }

    def get_email_service_info(self) -> Dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return self._build_error_response(
                "SMSPARTNER_API_KEY missing", credits_type="mixed"
            )

        try:
            # MailPartner API uses same endpoint format as SMS API
            response = self._perform_request(
                "get",
                f"{self.API_BASE_EMAIL}/me",
                params={"apiKey": api_key},
                timeout=5,
            )
        except Exception as exc:  # pragma: no cover
            return self._build_error_response(str(exc), credits_type="mixed")

        if getattr(response, "status_code", None) != 200:
            status_code = getattr(response, "status_code", "unknown")
            # Try to get error details from response
            try:
                payload = self._safe_json(response)
                error_msg = f"HTTP error {status_code}"
                # Include API error message if available
                if payload.get("message"):
                    error_msg += f": {payload['message']}"
                elif payload.get("error"):
                    error_msg += f": {payload['error']}"
                error_response = self._build_error_response(
                    error_msg, credits_type="mixed"
                )
                error_response["details"] = payload
                return error_response
            except Exception:
                return self._build_error_response(
                    f"HTTP error {status_code}", credits_type="mixed"
                )

        payload = self._safe_json(response)
        if payload.get("success") is not True:
            code = payload.get("code", payload.get("error_code", "unknown"))
            error = payload.get("error", "")
            message = payload.get("message", payload.get("error_message", ""))
            error_msg = "API error"
            if error:
                error_msg += f": {error}"
            elif code != "unknown":
                error_msg += f" (code {code})"
            if message:
                error_msg += f": {message}"

            error_response = self._build_error_response(error_msg, credits_type="mixed")
            error_response["details"] = payload
            return error_response

        # Try both response formats (account.emailCredits or credits.creditMail)
        details = payload.get("account", {})
        credits_data = payload.get("credits", {})

        # Check for emailCredits in account or creditMail in credits
        email_credits = details.get("emailCredits")
        if email_credits is None:
            email_credits = credits_data.get("creditMail")

        return {
            "credits": email_credits,
            "credits_type": "mixed",
            "is_available": payload.get("success") and (email_credits or 0) > 0,
            "limits": {},
            "warnings": payload.get("warnings", []),
            "details": (
                details if details else credits_data if credits_data else payload
            ),
        }

    def get_voice_call_service_info(self) -> Dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return self._build_error_response(
                "SMSPARTNER_API_KEY missing", credits_type="time"
            )

        try:
            response = self._perform_request(
                "get",
                f"{self.API_BASE_VOICE}/me/{api_key}",
                timeout=5,
            )
        except Exception as exc:  # pragma: no cover
            return self._build_error_response(str(exc), credits_type="time")

        if getattr(response, "status_code", None) != 200:
            return self._build_error_response(
                f"HTTP error {getattr(response, 'status_code', 'unknown')}",
                credits_type="time",
            )

        payload = self._safe_json(response)

        # VoicePartner API may not always return "success" field
        # Check if we have credit info directly
        if "credit" in payload or payload.get("success") is True:
            remaining = float(payload.get("credit", 0))
            warnings = []
            if remaining <= 1:
                warnings.append("Critical voice credit balance")

            return {
                "credits": remaining,
                "credits_type": "time",
                "is_available": remaining > 0,
                "limits": {},
                "warnings": warnings,
                "details": payload,
            }

        # If no success and no credit, it's an error
        code = payload.get("code", payload.get("error_code", "unknown"))
        error = payload.get("error", "")
        message = payload.get("message", payload.get("error_message", ""))
        error_msg = "API error"
        if error:
            error_msg += f": {error}"
        elif code != "unknown":
            error_msg += f" (code {code})"
        if message:
            error_msg += f": {message}"

        error_response = self._build_error_response(error_msg, credits_type="time")
        # Include payload in details for debugging
        error_response["details"] = payload
        return error_response

    # ------------------------------------------------------------------
    # Senders
    # ------------------------------------------------------------------

    def send_sms(self, **kwargs: Any) -> bool:
        risk = self.calculate_sms_delivery_risk()
        if not risk.get("should_send", True):
            self._fail_from_risk(risk, "SMS risk assessment failed")
            return False

        phone = self._get_missive_value("recipient_phone")
        if not phone:
            self._update_status(MissiveStatus.FAILED, error_message="Phone missing")
            return False

        api_key = self._get_api_key()
        if not api_key:
            self._update_status(
                MissiveStatus.FAILED, error_message="SMSPARTNER_API_KEY missing"
            )
            return False

        message = self._get_message_text()
        options = self._merge_options(**kwargs)

        payload: Dict[str, Any] = {
            "apiKey": api_key,
            "phoneNumbers": phone,
            "message": message,
            "sender": options.get(
                "sender", self._config.get("SMSPARTNER_SENDER", "Missive")
            ),
            "gamme": 1,
        }

        tag = (
            options.get("tag") or f"missive_{self._get_missive_value('id', 'unknown')}"
        )
        payload["tag"] = tag

        webhook_url = options.get("webhook_url") or self._config.get(
            "SMSPARTNER_WEBHOOK_URL"
        )
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
                f"{self.API_BASE_SMS}/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover - network layer
            message = f"Error calling SMSPartner API: {exc}"
            self._update_status(MissiveStatus.FAILED, error_message=message)
            self._create_event("failed", message)
            return False

        if result.get("success") is True:
            message_id = result.get("message_id") or result.get("messageId")
            cost = result.get("cost", 0)
            currency = result.get("currency", "EUR")
            segments = result.get("nb_sms", 1)

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=str(message_id) if message_id else None,
            )
            self._create_event(
                "sent",
                f"SMS sent via SMSPartner ({segments} segment(s), {cost}{currency})",
            )
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status(MissiveStatus.FAILED, error_message=error_msg)
        self._create_event("failed", error_msg)
        return False

    def send_email(self, **kwargs: Any) -> bool:
        risk = self.calculate_email_delivery_risk()
        if not risk.get("should_send", True):
            self._fail_from_risk(risk, "Email risk assessment failed")
            return False

        email = self._get_missive_value("recipient_email")
        if not email:
            self._update_status(MissiveStatus.FAILED, error_message="Email missing")
            return False

        api_key = self._get_api_key()
        if not api_key:
            self._update_status(
                MissiveStatus.FAILED, error_message="SMSPARTNER_API_KEY missing"
            )
            return False

        options = self._merge_options(**kwargs)
        from_email = self._config.get("DEFAULT_FROM_EMAIL", "noreply@example.com")
        from_name = self._config.get("DEFAULT_FROM_NAME", "")

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
                f"{self.API_BASE_EMAIL}/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover
            message = f"Error calling Mail Partner API: {exc}"
            self._update_status(MissiveStatus.FAILED, error_message=message)
            self._create_event("failed", message)
            return False

        if result.get("success") is True:
            message_id = result.get("messageId") or result.get("message_id")
            cost = result.get("cost", 0)
            currency = result.get("currency", "EUR")
            nb_mail = result.get("nbMail", 1)
            scheduled = result.get("scheduledDeliveryDate")

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=str(message_id) if message_id else None,
            )
            event_msg = (
                f"Email sent via Mail Partner ({nb_mail} email(s), {cost}{currency})"
            )
            if scheduled:
                event_msg += f" - scheduled for {scheduled}"
            self._create_event("sent", event_msg)
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status(MissiveStatus.FAILED, error_message=error_msg)
        self._create_event("failed", error_msg)
        return False

    def send_voice_call(self, **kwargs: Any) -> bool:
        risk = self.calculate_voice_call_delivery_risk()
        if not risk.get("should_send", True):
            self._fail_from_risk(risk, "Voice call risk assessment failed")
            return False

        phone = self._get_missive_value("recipient_phone")
        api_key = self._get_api_key()
        if not phone or not api_key:
            self._update_status(
                MissiveStatus.FAILED,
                error_message="Phone missing or SMSPARTNER_API_KEY missing",
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
                f"{self.API_BASE_VOICE}/tts/send",
                json_payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover
            message = f"Error calling Voice Partner API: {exc}"
            self._update_status(MissiveStatus.FAILED, error_message=message)
            self._create_event("failed", message)
            return False

        if result.get("success") is True:
            campaign_id = result.get("campaignId")
            duration = result.get("duration", 0)
            cost = result.get("cost", 0)
            currency = result.get("currency", "EUR")

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=str(campaign_id) if campaign_id else None,
            )
            self._create_event(
                "sent",
                f"Voice message sent via Voice Partner ({duration}s, {cost}{currency})",
            )
            return True

        error_msg = self._format_sms_errors(result)
        self._update_status(MissiveStatus.FAILED, error_message=error_msg)
        self._create_event("failed", error_msg)
        return False

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def cancel_sms(self, **kwargs: Any) -> bool:
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "delete",
                f"{self.API_BASE_SMS}/message-cancel/{external_id}",
                params={"apiKey": api_key},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:  # pragma: no cover
            return False

        if result.get("success") is True:
            self._create_event("cancelled", "SMS cancelled via SMSPartner")
            return True
        return False

    def cancel_email(self, **kwargs: Any) -> bool:
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "get",
                f"{self.API_BASE_EMAIL}/message-cancel",
                params={"apiKey": api_key, "messageId": external_id},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:  # pragma: no cover
            return False

        if result.get("success") is True:
            self._create_event("cancelled", "Email cancelled via Mail Partner")
            return True
        return False

    def cancel_voice_call(self, **kwargs: Any) -> bool:
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return False

        api_key = self._get_api_key()
        if not api_key:
            return False

        try:
            response = self._perform_request(
                "delete",
                f"{self.API_BASE_VOICE}/campaign/cancel/{api_key}/{external_id}",
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception:  # pragma: no cover
            return False

        if result.get("success") is True:
            self._create_event("cancelled", "Voice message cancelled via Voice Partner")
            return True
        return False

    # ------------------------------------------------------------------
    # Delivery status
    # ------------------------------------------------------------------

    def check_sms_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        external_id = self._get_missive_value("external_id")
        phone = self._get_missive_value("recipient_phone")
        if not external_id:
            return self._build_delivery_status_error("Missing external_id")
        if not phone:
            return self._build_delivery_status_error("Recipient phone missing")

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error("SMSPARTNER_API_KEY missing")

        try:
            response = self._perform_request(
                "get",
                f"{self.API_BASE_SMS}/message-status",
                params={
                    "apiKey": api_key,
                    "phoneNumber": phone,
                    "messageId": external_id,
                },
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover
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

    def check_email_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return self._build_delivery_status_error(
                "Missing external_id", include_email_fields=True
            )

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error(
                "SMSPARTNER_API_KEY missing", include_email_fields=True
            )

        try:
            response = self._perform_request(
                "get",
                f"{self.API_BASE_EMAIL}/bulk-status",
                params={"apiKey": api_key, "messageId": external_id},
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover
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

    def check_voice_call_delivery_status(self, **kwargs: Any) -> Dict[str, Any]:
        external_id = self._get_missive_value("external_id")
        if not external_id:
            return self._build_delivery_status_error("Missing external_id")

        api_key = self._get_api_key()
        if not api_key:
            return self._build_delivery_status_error("SMSPARTNER_API_KEY missing")

        try:
            response = self._perform_request(
                "get",
                f"{self.API_BASE_VOICE}/campaign/{api_key}/{external_id}",
                timeout=5,
            )
            result = self._safe_json(response)
        except Exception as exc:  # pragma: no cover
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

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def validate_sms_webhook_signature(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        allowed_ips = self._config.get("SMSPARTNER_WEBHOOK_IPS")
        if not allowed_ips:
            return True, ""

        client_ip = headers.get("X-Forwarded-For") or headers.get("X-Real-IP")
        if not client_ip:
            return False, "Missing client IP header"

        try:
            network = ipaddress.ip_network(allowed_ips, strict=False)
            if ipaddress.ip_address(client_ip) not in network:
                return False, f"IP {client_ip} not allowed"
        except ValueError:
            allowed_list = [ip.strip() for ip in allowed_ips.split(",")]
            if client_ip not in allowed_list:
                return False, f"IP {client_ip} not allowed"

        return True, ""

    def handle_sms_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
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
        self._create_event("webhook", json.dumps(normalized))
        return True, "", normalized

    def extract_sms_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        result = (
            payload.get("message_id")
            or payload.get("messageId")
            or payload.get("tag", "").replace("missive_", "")
        )
        return str(result) if result else None

    def validate_email_webhook_signature(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        return self.validate_sms_webhook_signature(payload, headers)

    def handle_email_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        message_id = self.extract_email_missive_id(payload)
        if not message_id:
            return False, "message_id missing", None
        normalized = {
            "message_id": message_id,
            "event": payload.get("event", "unknown").lower(),
            "raw": payload,
        }
        self._create_event("webhook", json.dumps(normalized))
        return True, "", normalized

    def extract_email_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        tag = payload.get("tag", "")
        if tag and isinstance(tag, str) and tag.startswith("missive_"):
            return tag.replace("missive_", "")  # type: ignore[no-any-return]
        result = payload.get("messageId") or payload.get("message_id")
        if result and isinstance(result, (str, int)):
            return str(result)
        return None

    def validate_voice_call_webhook_signature(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        return self.validate_sms_webhook_signature(payload, headers)

    def handle_voice_call_webhook(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        campaign_id = payload.get("campaignId") or payload.get("campaign_id")
        if not campaign_id:
            return False, "campaignId missing", None
        normalized = {
            "message_id": str(campaign_id),
            "event": payload.get("status", "unknown").lower(),
            "raw": payload,
        }
        self._create_event("webhook", json.dumps(normalized))
        return True, "", normalized

    def extract_voice_call_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        return payload.get("campaignId") or payload.get("campaign_id")

    def extract_notification_missive_id(self, payload: Dict[str, Any]) -> Optional[str]:
        return payload.get("message_id") or payload.get("messageId")

    def extract_push_notification_missive_id(
        self, payload: Dict[str, Any]
    ) -> Optional[str]:
        return payload.get("message_id") or payload.get("messageId")

    def extract_branded_missive_id(
        self, payload: Dict[str, Any], brand_name: Optional[str] = None
    ) -> Optional[str]:
        return self.extract_sms_missive_id(payload)

    def extract_event_type(self, payload: Dict[str, Any]) -> str:
        result = payload.get("status") or payload.get("event", "unknown")
        return str(result)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_sms_errors(self, result: Dict[str, Any]) -> str:
        errors = result.get("errors", [])
        if errors:
            return "; ".join(err.get("message", "") for err in errors)
        code = result.get("code")
        message = result.get("message", "")
        return self._get_error_message(code, message)


__all__ = ["SMSPartnerProvider"]

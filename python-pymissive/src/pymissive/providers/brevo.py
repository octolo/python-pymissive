"""Brevo (ex Sendinblue) email provider - API v4 and SMTP modes."""

import contextlib
import json
from typing import Any

from .base import MissiveProviderBase


class BrevoAPIProvider(MissiveProviderBase):
    """Abstract base class for Brevo providers using SDK v4."""

    # -----------------------
    # Metadata / configuration
    # -----------------------
    name = "brevo"
    display_name = "Brevo"
    required_packages = ["brevo-python>=4.0"]
    config_keys = ["EMAIL_API_KEY", "SMS_API_KEY", "WHATSAPP_API_KEY"]
    description = "Complete CRM platform (Email, SMS, Marketing automation)"
    documentation_url = "https://developers.brevo.com"
    site_url = "https://www.brevo.com"
    brands = ["WhatsApp"]

    fields_associations = {
        "id": "id",
        "url": "url",
        "type": "type",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "occurred_at": ["occurred_at", "_date", "date", "trace._date"],
        "event": ["event", "trace.event"],
        "description": ["reason", "trace.reason", "event", "trace.event"],
        "external_id": ["message_id", "_message_id", "message-id"],
        "email": ["email", "trace.email"],
        "sender_email": ["_from", "trace._from", "sender_email"],
    }
    events_association = {
        "request": "request",
        "requests": "request",
        "sent": "sent",
        "hardBounce": "hard_bounce",
        "softBounce": "soft_bounce",
        "blocked": "blocked",
        "spam": "spam",
        "delivered": "delivered",
        "click": "click",
        "invalid": "invalid",
        "deferred": "deferred",
        "opened": "opened",
    }

    #########################################################
    # Initialization / API clients (Brevo v4)
    #########################################################

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        if not hasattr(self, "attachments"):
            self.attachments = []
        self._email_api_key = self._get_config_or_env("EMAIL_API_KEY")
        self._sms_api_key = self._get_config_or_env("SMS_API_KEY")
        self._whatsapp_api_key = self._get_config_or_env("WHATSAPP_API_KEY")
        self._email_client = None
        self._sms_client = None
        self._whatsapp_client = None
        self._webhooks_client = None

    def _get_email_client(self):
        """Return the Brevo API client for email."""
        if self._email_client is None:
            from brevo import Brevo

            self._email_client = Brevo(api_key=self._email_api_key)
        return self._email_client

    def _get_sms_client(self):
        """Return the Brevo API client for SMS."""
        if self._sms_client is None:
            from brevo import Brevo

            self._sms_client = Brevo(api_key=self._sms_api_key)
        return self._sms_client

    def _get_whatsapp_client(self):
        """Return the Brevo API client for WhatsApp."""
        if self._whatsapp_client is None:
            from brevo import Brevo

            self._whatsapp_client = Brevo(api_key=self._whatsapp_api_key)
        return self._whatsapp_client

    def _get_webhooks_client(self):
        """Return the Brevo webhooks client (uses email API key)."""
        if self._webhooks_client is None:
            from brevo import Brevo

            self._webhooks_client = Brevo(api_key=self._email_api_key)
        return self._webhooks_client

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        """Return the normalized type of webhook/email/SMS."""
        if data.get("type") == "transactional":
            return "email"
        elif data.get("type") == "marketing":
            return "email_marketing"
        elif data.get("type") == "sms":
            return "sms"
        return "unknown"

    #########################################################
    # Webhooks (Brevo v4)
    #########################################################

    def get_webhooks(self):
        """Return the Brevo webhooks."""
        client = self._get_webhooks_client()
        response = client.webhooks.get_webhooks()
        webhooks = getattr(response, "webhooks", None)
        if webhooks is None and hasattr(response, "model_dump"):
            webhooks = response.model_dump().get("webhooks", [])
        webhooks = webhooks or []
        return [self._webhook_to_dict(w) for w in webhooks]

    def _webhook_to_dict(self, webhook) -> dict[str, Any]:
        """Convert v4 webhook object to dict for compatibility."""
        if isinstance(webhook, dict):
            return webhook
        return {
            "id": getattr(webhook, "id", webhook),
            "url": getattr(webhook, "url", ""),
            "type": getattr(webhook, "type", ""),
            "description": getattr(webhook, "description", ""),
            "channel": getattr(webhook, "channel", ""),
            "events": getattr(webhook, "events", []),
        }

    #########################################################
    # Attachments
    #########################################################

    def _build_attachments(self, attachments: list) -> list:
        """Build v4 attachment list from kwargs."""
        if not attachments:
            return []
        from brevo.transactional_emails import SendTransacEmailRequestAttachmentItem

        return [
            SendTransacEmailRequestAttachmentItem(
                name=a["name"],
                content=self._to_base64(a["content"]),
            )
            for a in attachments
        ]

    def _event_to_payload(self, event: Any) -> dict[str, Any]:
        """Convert event object to dict for _normalize_event_email.

        Brevo v4 returns Pydantic model objects (attributes, not dict keys).
        """
        if isinstance(event, dict):
            return event
        if hasattr(event, "model_dump"):
            return event.model_dump()
        if hasattr(event, "dict"):
            return event.dict()
        return {k: v for k, v in vars(event).items() if not k.startswith("_")}

    #########################################################
    # Email sending (Brevo v4)
    #########################################################

    def delete_blocked_emails(self, kwargs: dict[str, Any]) -> bool:
        with contextlib.suppress(Exception):
            client = self._get_email_client()
            for recipient in kwargs.get("recipients", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(
                    recipient["email"]
                )
            for recipient in kwargs.get("cc", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(
                    recipient["email"]
                )
            for recipient in kwargs.get("bcc", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(
                    recipient["email"]
                )
        return True

    def send_email(self, **kwargs) -> dict[str, Any]:
        """Send email via Brevo API v4."""
        from brevo.transactional_emails import (
            SendTransacEmailRequestBccItem,
            SendTransacEmailRequestCcItem,
            SendTransacEmailRequestReplyTo,
            SendTransacEmailRequestSender,
            SendTransacEmailRequestToItem,
        )

        self.delete_blocked_emails(kwargs)
        sender = kwargs.get("sender", {})
        recipients = kwargs.get("recipients", [])
        reply_to = kwargs.get("reply_to")
        cc = kwargs.get("cc", [])
        bcc = kwargs.get("bcc", [])
        attachments = self._build_attachments(kwargs.get("attachments", []))

        send_kwargs: dict[str, Any] = {
            "subject": kwargs["subject"],
            "sender": SendTransacEmailRequestSender(
                email=sender["email"],
                name=sender.get("name", ""),
            ),
            "to": [
                SendTransacEmailRequestToItem(
                    email=r["email"],
                    name=r.get("name", ""),
                )
                for r in recipients
            ],
        }
        if kwargs.get("body"):
            send_kwargs["html_content"] = kwargs["body"]
        if kwargs.get("body_text"):
            send_kwargs["text_content"] = kwargs["body_text"]
        if reply_to:
            send_kwargs["reply_to"] = SendTransacEmailRequestReplyTo(
                email=reply_to["email"],
                name=reply_to.get("name", ""),
            )
        if cc:
            send_kwargs["cc"] = [
                SendTransacEmailRequestCcItem(email=r["email"], name=r.get("name", ""))
                for r in cc
            ]
        if bcc:
            send_kwargs["bcc"] = [
                SendTransacEmailRequestBccItem(
                    email=r["email"], name=r.get("name", "")
                )
                for r in bcc
            ]
        if attachments:
            send_kwargs["attachment"] = attachments

        client = self._get_email_client()
        response = client.transactional_emails.send_transac_email(**send_kwargs)
        return self._response_to_dict(response)

    def _response_to_dict(self, response) -> dict[str, Any]:
        """Convert v4 Pydantic response to dict."""
        if isinstance(response, dict):
            return {k: str(v) for k, v in response.items()}
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        else:
            data = dict(vars(response))
        return {k: str(v) for k, v in data.items() if not k.startswith("_")}

    def status_email(self, **kwargs) -> dict[str, Any]:
        """Get the status of an email via Brevo API v4."""
        client = self._get_email_client()
        response = client.transactional_emails.get_email_event_report(
            message_id=kwargs["external_id"]
        )
        events = getattr(response, "events", []) or []
        return [self._event_to_payload(event) for event in events]

    def set_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo events."""
        client = self._get_webhooks_client()
        events = [
            e for e in self.events_association.keys() if e != "requests"
        ]
        response = client.webhooks.create_webhook(
            url=webhook_data.get("url"),
            description="Missive webhook email",
            events=events,
            channel="email",
            type="transactional",
        )
        webhook_id = getattr(response, "id", response)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def delete_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.delete_webhook(webhook_id)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def update_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo email webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_email(self, webhook_id: str):
        """Return the Brevo webhook."""
        webhooks = self.get_webhooks_email()
        return next(
            (w for w in webhooks if str(w.get("id")) == str(webhook_id)), None
        )

    def get_webhooks_email(self):
        """Return only transactional email webhooks."""
        webhooks = self.get_webhooks()
        return [
            w
            for w in webhooks
            if str(w.get("type", "")).lower() == "transactional"
            and str(w.get("channel", "")).lower() in ("email", "")
        ]

    def handle_webhook_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    #########################################################
    # SMS (Brevo v4 - uses direct API for content)
    #########################################################

    def send_sms(self, **kwargs) -> dict[str, Any]:
        """Send SMS via Brevo API v4. Uses direct HTTP call as v4 SDK omits content param."""
        import json as _json
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        recipient = str(kwargs["recipients"][0].get("phone", ""))
        sender_name = kwargs["sender"].get("name", "Missive")
        content = kwargs.get("body_text", "")

        body = _json.dumps(
            {
                "sender": sender_name,
                "recipient": recipient,
                "content": content,
            }
        ).encode("utf-8")
        req = Request(
            "https://api.brevo.com/v3/transactionalSMS/sms",
            data=body,
            headers={
                "api-key": self._sms_api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req) as resp:
                return self._response_to_dict(_json.loads(resp.read().decode()))
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            raise RuntimeError(f"Brevo SMS API error {e.code}: {body}") from e

    def set_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo SMS events."""
        client = self._get_webhooks_client()
        response = client.webhooks.create_webhook(
            url=webhook_data.get("url"),
            description="Missive webhook SMS",
            events=list(self.events_association.keys()),
            channel="sms",
            type="transactional",
        )
        return self.get_normalize_webhook_id({"id": getattr(response, "id", response)})

    def delete_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        client.webhooks.delete_webhook(int(webhook_data.get("id")))
        return self.get_normalize_webhook_id({"id": webhook_data.get("id")})

    def update_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo SMS webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_sms(self, webhook_id: str):
        """Return the Brevo SMS webhook."""
        webhooks = self.get_webhooks_sms()
        return next(
            (w for w in webhooks if str(w.get("id")) == str(webhook_id)), None
        )

    def get_webhooks_sms(self):
        """Return only transactional SMS webhooks."""
        webhooks = self.get_webhooks()
        return [w for w in webhooks if w.get("type") == "transactional" and w.get("channel") == "sms"]

    def handle_webhook_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    #########################################################
    # WhatsApp (Brevo v4)
    #########################################################

    def send_branded(self, **kwargs) -> dict[str, Any]:
        """Send a branded message via Brevo API."""
        return self.send_whatsapp(**kwargs)

    def send_whatsapp(self, **kwargs) -> dict[str, Any]:
        """Send WhatsApp via Brevo API v4."""
        from brevo.transactional_whats_app import SendWhatsappMessageRequestText

        recipients = [str(r["phone"]) for r in kwargs.get("recipients", [])]
        sender = "+33614397083"
        text = kwargs.get("body_text", "")

        request = SendWhatsappMessageRequestText(
            contact_numbers=recipients,
            sender_number=sender,
            text=text,
        )
        client = self._get_whatsapp_client()
        response = client.transactional_whats_app.send_whatsapp_message(
            request=request
        )
        return self._response_to_dict(response)

    def set_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo WhatsApp events."""
        client = self._get_webhooks_client()
        response = client.webhooks.create_webhook(
            url=webhook_data.get("url"),
            description="Missive webhook WhatsApp",
            events=list(self.events_association.keys()),
            channel="whatsapp",
            type="transactional",
        )
        return self.get_normalize_webhook_id({"id": getattr(response, "id", response)})

    def delete_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        client.webhooks.delete_webhook(int(webhook_data.get("id")))
        return self.get_normalize_webhook_id({"id": webhook_data.get("id")})

    def update_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo WhatsApp webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_whatsapp(self, webhook_id: str):
        """Return the Brevo WhatsApp webhook."""
        webhooks = self.get_webhooks_whatsapp()
        return next(
            (w for w in webhooks if str(w.get("id")) == str(webhook_id)), None
        )

    def get_webhooks_whatsapp(self):
        """Return only transactional WhatsApp webhooks."""
        webhooks = self.get_webhooks()
        return [
            w
            for w in webhooks
            if w.get("type") == "transactional"
            and w.get("channel") == "whatsapp"
        ]

    def handle_webhook_whatsapp(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        payload = json.loads(payload)
        event = payload.get("event")
        message_id = payload.get("message-id") or payload.get("messageId")
        return {
            "recipient": payload.get("phone"),
            "external_id": str(message_id),
            "event": self.events_association.get(event, "unknown"),
            "description": payload.get("reason") or event,
            "occurred_at": payload.get("date"),
            "trace": payload,
        }

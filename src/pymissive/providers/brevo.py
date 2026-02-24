"""Brevo (ex Sendinblue) email provider - API and SMTP modes."""

import contextlib
import json
from typing import Any
from .base import MissiveProviderBase


class BrevoAPIProvider(MissiveProviderBase):
    """Abstract base class for Brevo providers."""

    # -----------------------
    # Metadata / configuration
    # -----------------------
    name = "brevo"
    display_name = "Brevo"
    required_packages = ["brevo-python"]
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
        "occurred_at": ["occurred_at","_date", "date", "trace._date"],
        "event": ["event", "trace.event"],
        "description": ["reason", "trace.reason", "event", "trace.event"],
        "external_id": ["message_id", "_message_id", "message-id"],
        "email": ["email", "trace.email"],
        "sender_email": ["_from", "trace._from", "sender_email",],
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
    # Initialization / API clients
    #########################################################

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        if not hasattr(self, "attachments"):
            self.attachments = []
        self._email_api_key = self._get_config_or_env("EMAIL_API_KEY")
        self._sms_api_key = self._get_config_or_env("SMS_API_KEY")
        self._whatsapp_api_key = self._get_config_or_env("WHATSAPP_API_KEY")
        self._webhooks_api = None
        self._transactional_email_api = None
        self._transactional_sms_api = None
        self._transactional_whatsapp_api = None

    def get_api_client(self, api_key: str):
        """Return the Brevo API client."""
        from brevo_python import ApiClient, Configuration
        configuration = Configuration()
        configuration.api_key["api-key"] = api_key
        configuration.api_key['partner-key'] = api_key
        return ApiClient(configuration)

    def _get_transactional_email_api(self):
        """Return the Brevo transactional API instance."""
        if self._transactional_email_api is None:
            from brevo_python import TransactionalEmailsApi
            api_client = self.get_api_client(self._email_api_key)
            self._transactional_email_api = TransactionalEmailsApi(api_client)
        return self._transactional_email_api

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
    # Webhooks
    #########################################################

    def _get_webhooks_api(self):
        """Return the Brevo webhooks API instance."""
        if self._webhooks_api is None:
            from brevo_python import WebhooksApi
            api_client = self.get_api_client(self._email_api_key)
            self._webhooks_api = WebhooksApi(api_client)
        return self._webhooks_api

    def get_webhooks(self):
        """Return the Brevo webhooks."""
        wbhs = self._get_webhooks_api()
        return wbhs.get_webhooks().webhooks

    #########################################################
    # Attachments
    #########################################################

    def _add_attachments_email(self, email, attachments):
        if not attachments:
            return
        from brevo_python import SendSmtpEmailAttachment

        email.attachment = [
            SendSmtpEmailAttachment(
                name=a["name"],
                content=self._to_base64(a["content"]),
            )
            for a in attachments
        ]

    def _event_to_payload(self, event: Any) -> dict[str, Any]:
        """Convert GetEmailEventReportEvents object to dict for _normalize_event_email.

        brevo-python returns OpenAPI model objects (attributes, not dict keys).
        See: https://github.com/getbrevo/brevo-python/blob/main/docs/GetEmailEventReportEvents.md
        """
        if isinstance(event, dict):
            return event
        to_dict = getattr(event, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return {k: v for k, v in event.__dict__.items() if k != "to_dict"}

    #########################################################
    # Email sending
    #########################################################

    def delete_blocked_emails(self, kwargs: dict[str, Any]) -> bool:
        with contextlib.suppress(Exception):
            api_instance = self._get_transactional_email_api()
            for recipient in kwargs.get("recipients", []):
                api_instance.smtp_blocked_contacts_email_delete(recipient["email"])
            for recipient in kwargs.get("cc", []):
                api_instance.smtp_blocked_contacts_email_delete(recipient["email"])
            for recipient in kwargs.get("bcc", []):
                api_instance.smtp_blocked_contacts_email_delete(recipient["email"])

    def _prepare_email(self, **kwargs):
        """Prepare the SendSmtpEmail object for sending."""
        from brevo_python import SendSmtpEmail
        email = SendSmtpEmail(subject=kwargs["subject"])
        self._add_sender(email, kwargs)
        self._add_content(email, kwargs)
        self._add_reply_to(email, kwargs)
        self._add_recipients(email, kwargs["recipients"])
        self._add_bcc_or_cc(email, kwargs.get("bcc", []), "bcc")
        self._add_bcc_or_cc(email, kwargs.get("cc", []), "cc")
        self._add_attachments_email(email, kwargs.get("attachments", []))
        return email

    def _add_recipients(self, email, recipients):
        from brevo_python import SendSmtpEmailTo
        email.to = [
            SendSmtpEmailTo(email=recipient["email"], name=recipient.get("name", ""))
            for recipient in recipients
        ]

    def _add_sender(self, email, kwargs):
        from brevo_python import SendSmtpEmailSender
        sender = kwargs.get("sender")
        email.sender = SendSmtpEmailSender(
            email=sender["email"],
            name=sender.get("name", "")
        )

    def _add_content(self, email, kwargs):
        if kwargs.get("body"):
            email.html_content = kwargs["body"]
        if kwargs.get("body_text"):
            email.text_content = kwargs["body_text"]

    def _add_reply_to(self, email, kwargs):
        reply_to = kwargs.get("reply_to")
        if reply_to:
            from brevo_python import SendSmtpEmailReplyTo
            email.reply_to = SendSmtpEmailReplyTo(
                email=reply_to["email"],
                name=reply_to.get("name", "")
            )

    def _add_bcc_or_cc(self, email, recipients, key):
        if not recipients or key not in ["cc", "bcc"]:
            return
        if key == "cc":
            from brevo_python import SendSmtpEmailCc
            recipient_class = SendSmtpEmailCc
        elif key == "bcc":
            from brevo_python import SendSmtpEmailBcc
            recipient_class = SendSmtpEmailBcc
        setattr(email, key, [
            recipient_class(email=r["email"], name=r.get("name", ""))
            for r in recipients
        ])

    def send_email(self, **kwargs) -> dict[str, Any]:
        """Send email via Brevo API."""
        self.delete_blocked_emails(kwargs)
        email = self._prepare_email(**kwargs)
        api_instance = self._get_transactional_email_api()
        response = api_instance.send_transac_email(email)
        return {field: str(getattr(response, field)) for field in response.__dict__}

    def status_email(self, **kwargs) -> dict[str, Any]:
        """Get the status of an email via Brevo API."""
        api_instance = self._get_transactional_email_api()
        response = api_instance.get_email_event_report(
            message_id=kwargs["external_id"]
        )
        events = getattr(response, "events", []) or []
        return [self._event_to_payload(event) for event in events]

    def set_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo events."""
        from brevo_python import CreateWebhook
        wbhs = self._get_webhooks_api()
        events = [event for event in self.events_association.keys() if event != "requests"]
        create_webhook = CreateWebhook(
            url=webhook_data.get("url"),
            description="Missive webhook email",
            events=events,
            channel="email",
            type="transactional",
        )
        wbh = wbhs.create_webhook(create_webhook)
        return self.get_normalize_webhook_id({"id": wbh.id})

    def delete_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        wbhs = self._get_webhooks_api()
        return wbhs.delete_webhook(webhook_data.get("id"))

    def update_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Return the Brevo webhooks."""
        from brevo_python import UpdateWebhook
        wbhs = self._get_webhooks_api()
        update = UpdateWebhook(url=webhook_data.get("url"))
        webhook_id = webhook_data.get("id")
        wbhs.update_webhook(webhook_id, update)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_email(self, webhook_id: str):
        """Return the Brevo webhook."""
        wbhs = self._get_webhooks_api()
        return next((wbh for wbh in wbhs if str(wbh.id) == str(webhook_id)), None)

    def get_webhooks_email(self):
        """Return only transactional email webhooks."""
        webhooks = self.get_webhooks()
        return [webhook for webhook in webhooks if webhook["type"] == "transactional"]

    def handle_webhook_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        payload = payload.decode("utf-8")
        return json.loads(payload)
        

    #########################################################
    # SMS
    #########################################################

    def _get_transactional_sms_api(self):
        """Return the Brevo transactional SMS API instance."""
        if self._transactional_sms_api is None:
            from brevo_python import TransactionalSMSApi
            api_client = self.get_api_client(self._sms_api_key)
            self._transactional_sms_api = TransactionalSMSApi(api_client)
        return self._transactional_sms_api

    def _prepare_sms(self, **kwargs):
        """Prepare the SendSmsEmail object for sending."""
        from brevo_python import SendTransacSms
        sms = SendTransacSms(
            sender=kwargs["sender"].get("name"),
            recipient=str(kwargs["recipients"][0].get("phone")),
            content=kwargs.get("body_text"),
        )
        return sms

    def send_sms(self, **kwargs) -> dict[str, Any]:
        """Send SMS via Brevo API."""
        sms = self._prepare_sms(**kwargs)
        api_instance = self._get_transactional_sms_api()
        response = api_instance.send_transac_sms(sms)
        return {field: str(getattr(response, field)) for field in response.__dict__}

    def set_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo events."""
        from brevo_python import CreateWebhook
        wbhs = self._get_webhooks_api()
        create_webhook = CreateWebhook(
            url=webhook_data.get("url"),
            description="Missive webhook SMS",
            events=list(self.events_association.keys()),
            channel="sms",
            type="transactional",
        )
        return wbhs.create_webhook(create_webhook)

    def delete_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        wbhs = self._get_webhooks_api()
        return wbhs.delete_webhook(webhook_data.get("id"))

    def update_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo SMS webhook."""
        from brevo_python import UpdateWebhook
        wbhs = self._get_webhooks_api()
        update = UpdateWebhook(url=webhook_data.get("url"))
        webhook_id = webhook_data.get("id")
        wbhs.update_webhook(webhook_id, update)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_sms(self, webhook_id: str):
        """Return the Brevo webhook."""
        wbhs = self._get_webhooks_api()
        return next((wbh for wbh in wbhs if str(wbh.id) == str(webhook_id)), None)

    def get_webhooks_sms(self):
        """Return only transactional SMS webhooks."""
        webhooks = self.get_webhooks()
        return [webhook for webhook in webhooks if webhook["type"] == "transactional"]

    def handle_webhook_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        payload = payload.decode("utf-8")
        return json.loads(payload)


    #########################################################
    # Whatsapp
    #########################################################

    def _get_transactional_whatsapp_api(self):
        """Return the Brevo transactional WhatsApp API instance."""
        if self._transactional_whatsapp_api is None:
            from brevo_python import TransactionalWhatsAppApi
            api_client = self.get_api_client(self._whatsapp_api_key)
            self._transactional_whatsapp_api = TransactionalWhatsAppApi(api_client)
        return self._transactional_whatsapp_api

    def send_branded(self, **kwargs) -> dict[str, Any]:
        """Send a branded message via Brevo API."""
        return self.send_whatsapp(**kwargs)

    def send_whatsapp(self, **kwargs) -> dict[str, Any]:
        """Send WhatsApp via Brevo API."""
        from brevo_python import SendWhatsappMessage
        recipients = [str(recipient["phone"]) for recipient in kwargs.get("recipients", [])]
        sender = "+33614397083"
        message = SendWhatsappMessage(
            contact_numbers=recipients,
            sender_number=sender,
            text=kwargs.get("body_text"),
        )
        api_instance = self._get_transactional_whatsapp_api()
        response = api_instance.send_whatsapp_message(message)
        return {field: str(getattr(response, field)) for field in response.__dict__}

    def set_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo events."""
        from brevo_python import CreateWebhook
        wbhs = self._get_webhooks_api()
        create_webhook = CreateWebhook(
            url=webhook_data.get("url"),
            description="Missive webhook WhatsApp",
            events=list(self.events_association.keys()),
            channel="whatsapp",
            type="transactional",
        )
        return wbhs.create_webhook(create_webhook)

    def delete_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        wbhs = self._get_webhooks_api()
        return wbhs.delete_webhook(webhook_data.get("id"))

    def update_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Return the Brevo webhooks."""
        from brevo_python import UpdateWebhook
        wbhs = self._get_webhooks_api()
        update = UpdateWebhook(url=webhook_data.get("url"))
        webhook_id = webhook_data.get("id")
        wbhs.update_webhook(webhook_id, update)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def get_webhook_whatsapp(self, webhook_id: str):
        """Return the Brevo webhook."""
        wbhs = self._get_webhooks_api()
        return next((wbh for wbh in wbhs if str(wbh.id) == str(webhook_id)), None)

    def get_webhooks_whatsapp(self):
        """Return only transactional WhatsApp webhooks."""
        webhooks = self.get_webhooks()
        return [webhook for webhook in webhooks if webhook["type"] == "transactional"]
    
    def handle_webhook_whatsapp(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
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
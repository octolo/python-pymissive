"""Brevo (ex Sendinblue) email provider - API and SMTP modes."""

import contextlib
from typing import Any
from .base import MissiveProviderBase
import json


class BrevoAPIProvider(MissiveProviderBase):
    """Abstract base class for Brevo providers."""

    # -----------------------
    # Metadata / configuration
    # -----------------------
    name = "brevo"
    display_name = "Brevo"
    required_packages = ["brevo-python"]
    config_keys = ["API_KEY"]
    description = "Complete CRM platform (Email, SMS, Marketing automation)"
    documentation_url = "https://developers.brevo.com"
    site_url = "https://www.brevo.com"
    fields_associations = {
        "id": "id",
        "url": "url",
        "type": "type",
        "description": "description",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
    }
    events_association = {
        "sent": "sent",
        "hardBounce": "hard_bounce",
        "softBounce": "soft_bounce",
        "blocked": "blocked",
        "spam": "spam",
        "delivered": "delivered",
        "request": "request",
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
        self._api_key = self._get_config_or_env("API_KEY")
        self._webhooks_api = None
        self._transactional_api = None

    def get_api_client(self):
        """Return the Brevo API client."""
        from brevo_python import ApiClient, Configuration
        configuration = Configuration()
        configuration.api_key["api-key"] = self._api_key
        return ApiClient(configuration)

    def _get_transactional_api(self):
        """Return the Brevo transactional API instance."""
        if self._transactional_api is None:
            from brevo_python import TransactionalEmailsApi
            api_client = self.get_api_client()
            self._transactional_api = TransactionalEmailsApi(api_client)
        return self._transactional_api

    #########################################################
    # Attachments
    #########################################################

    def add_attachment_email(self, content: bytes | str, name: str) -> None:
        """Add an attachment to the email."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.attachments.append({"content": content, "name": name})

    def remove_attachment_email(self, name: str) -> None:
        """Remove an attachment from the email."""
        if not hasattr(self, "attachments"):
            return
        self.attachments = [att for att in self.attachments if att["name"] != name]

    #########################################################
    # Email sending
    #########################################################

    def delete_blocked_email(self, email: str) -> bool:
        with contextlib.suppress(Exception):
            api_instance = self._get_transactional_api()
            api_instance.smtp_blocked_contacts_email_delete(email)

    def prepare_email(self, **kwargs):
        """Prepare the SendSmtpEmail object for sending."""
        from brevo_python import SendSmtpEmail, SendSmtpEmailTo, SendSmtpEmailSender, SendSmtpEmailAttachment

        recipient_email = kwargs.get("recipient_email")
        sender_email = kwargs.get("sender_email")
        sender_name = kwargs.get("sender_name")
        subject = kwargs.get("subject")
        body = kwargs.get("body")
        body_text = kwargs.get("body_text")

        if not recipient_email:
            raise ValueError("recipient_email is required")
        if not sender_email:
            raise ValueError("sender_email is required")

        email = SendSmtpEmail(
            to=[SendSmtpEmailTo(email=recipient_email)],
            sender=SendSmtpEmailSender(email=sender_email, name=sender_name or ""),
            subject=subject or "",
        )

        if body:
            email.html_content = body
        if body_text:
            email.text_content = body_text

        # Reply-to / CC / BCC
        reply_to = kwargs.get("reply_to")
        if reply_to:
            email.reply_to = {"email": reply_to}

        cc = kwargs.get("cc")
        if cc:
            if isinstance(cc, list):
                email.cc = [SendSmtpEmailTo(email=email_addr) for email_addr in cc]
            else:
                email.cc = [SendSmtpEmailTo(email=cc)]

        bcc = kwargs.get("bcc")
        if bcc:
            if isinstance(bcc, list):
                email.bcc = [SendSmtpEmailTo(email=email_addr) for email_addr in bcc]
            else:
                email.bcc = [SendSmtpEmailTo(email=bcc)]

        return email

    def send_email(self, **kwargs) -> dict[str, Any]:
        """Send email via Brevo API."""
        self.delete_blocked_email(kwargs.get("recipient_email"))
        email = self.prepare_email(**kwargs)
        api_instance = self._get_transactional_api()
        response = api_instance.send_transac_email(email)
        return {field: str(getattr(response, field)) for field in response.__dict__}

    #########################################################
    # Webhooks
    #########################################################

    def _get_webhooks_api(self):
        """Return the Brevo webhooks API instance."""
        if self._webhooks_api is None:
            from brevo_python import WebhooksApi
            api_client = self.get_api_client()
            self._webhooks_api = WebhooksApi(api_client)
        return self._webhooks_api

    def set_webhook_email(self, webhook_url: str) -> bool:
        """Configure a webhook to receive Brevo events."""
        from brevo_python import CreateWebhook, WebhooksApi
        wbhs = self._get_webhooks_api()
        create_webhook = CreateWebhook(
            url=webhook_url,
            description="Missive webhook",
            events=list(self.events_association.keys()),
            channel="email",
            type="transactional",
        )
        return wbhs.create_webhook(create_webhook)

    def get_webhooks(self):
        """Return the Brevo webhooks."""
        wbhs = self._get_webhooks_api()
        return wbhs.get_webhooks().webhooks

    def delete_webhook_email(self, webhook_id: str) -> bool:
        """Delete a webhook from Brevo."""
        wbhs = self._get_webhooks_api()
        provider, webhook_id = webhook_id.split("-")
        return wbhs.delete_webhook(webhook_id)

    def update_webhook_email(self, webhook_id: str, webhook_url: str) -> bool:
        """Return the Brevo webhooks."""
        from brevo_python import UpdateWebhook
        wbhs = self._get_webhooks_api()
        update = UpdateWebhook(url=webhook_url)
        provider, webhook_id = webhook_id.split("-")
        return wbhs.update_webhook(webhook_id, update)

    def get_webhooks_email(self):
        """Return only transactional email webhooks."""
        webhooks = self.get_webhooks()
        return [webhook for webhook in webhooks if webhook["type"] == "transactional"]

    def handle_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        print("okkkkkkkkkkkkkk payload", payload)
        payload = payload.decode("utf-8")
        payload = json.loads(payload)
        event = payload.get("event")
        message_id = payload.get("message-id") or payload.get("messageId")
        return {
            "external_id": str(message_id),
            "event": self.events_association.get(event, "unknown"),
            "occurred_at": payload.get("date"),
            "trace": payload,
        }

    #########################################################
    # Helpers
    #########################################################

    def get_external_id_email(self, payload: dict[str, Any]) -> str | None:
        """Extract the external ID from the Brevo webhook."""
        return payload.get("_message_id")

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        """Return the normalized type of webhook/email/SMS."""
        if data.get("type") == "transactional":
            return "email"
        elif data.get("type") == "marketing":
            return "email_marketing"
        elif data.get("type") == "sms":
            return "sms"
        return "unknown"

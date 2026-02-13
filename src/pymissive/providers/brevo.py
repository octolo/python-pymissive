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
        "request": "request",
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

    #########################################################
    # Email sending
    #########################################################

    def delete_blocked_emails(self, kwargs: dict[str, Any]) -> bool:
        with contextlib.suppress(Exception):
            api_instance = self._get_transactional_api()
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

    def handle_webhook_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        payload = payload.decode("utf-8")
        payload = json.loads(payload)
        event = payload.get("event")
        message_id = payload.get("message-id") or payload.get("messageId")
        return {
            "recipient": payload.get("email"),
            "external_id": str(message_id),
            "event": self.events_association.get(event, "unknown"),
            "description": payload.get("reason"),
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

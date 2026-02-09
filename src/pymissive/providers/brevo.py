"""Brevo (ex Sendinblue) email provider - API and SMTP modes."""

import base64
import smtplib
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any
import json
from .base import MissiveProviderBase


class BrevoProvider(MissiveProviderBase):
    """Abstract base class for Brevo providers."""
    abstract = True
    display_name = "Brevo"
    description = "Complete CRM platform (Email, SMS, Marketing automation)"
    documentation_url = "https://developers.brevo.com"
    site_url = "https://www.brevo.com"

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Brevo provider."""
        super().__init__(**kwargs)
        if not hasattr(self, "attachments"):
            self.attachments = []
        self._api_key = self._get_config_or_env("API_KEY")
        self._webhooks_api = None

    def get_webhooks(self):
        """Return the Brevo webhooks API instance."""
        from sib_api_v3_sdk import ApiClient, Configuration, WebhooksApi
        configuration = Configuration()
        configuration.api_key["api-key"] = self._api_key
        api_client = ApiClient(configuration)
        return WebhooksApi(api_client)

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

    def cancel_email(self) -> bool:
        """Cancel email sending (not supported by Brevo)."""
        return False

    def set_webhook(self, webhook_url: str, events: list[str] | None = None) -> bool:
        """Configure a webhook to receive Brevo events."""
        webhooks_api = self._get_webhooks_api()
        if not webhooks_api:
            return False

        try:
            from sib_api_v3_sdk import CreateWebhook
        except ImportError:
            return False

        if events is None:
            events = [
                "hard_bounce",
                "soft_bounce",
                "delivered",
                "spam",
                "request",
                "opened",
                "click",
                "invalid",
                "deferred",
                "blocked",
                "unsubscribed",
            ]

        try:
            webhook = CreateWebhook(
                url=webhook_url,
                description="Missive webhook",
                events=events,
            )
            webhooks_api.create_webhook(webhook)
            return True
        except Exception:
            return False

    def handle_webhook(self, payload: dict[str, Any], headers: dict[str, str]) -> tuple[bool, str, dict[str, Any] | None]:
        """Handle a Brevo webhook."""
        event = payload.get("event")
        message_id = payload.get("message-id") or payload.get("messageId")

        if not message_id:
            return False, "message-id missing", None

        normalized = {
            "message_id": str(message_id),
            "event": event or "unknown",
            "raw": payload,
        }

        return True, "", normalized

    def get_external_id_email(self, payload: dict[str, Any]) -> str | None:
        """Extract the external ID from the Brevo webhook."""
        return payload.get("_message_id")


class BrevoAPIProvider(BrevoProvider):
    """Brevo provider using REST API."""
    name = "brevo_api"
    display_name = "Brevo API"
    required_packages = ["sib-api-v3-sdk"]
    config_keys = ["API_KEY"]
    abstract = False

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Brevo API provider."""
        super().__init__(**kwargs)
        self._transactional_api = None

    def _get_transactional_api(self):
        """Return the Brevo transactional API instance."""
        if self._transactional_api is None:
            if not self._api_key:
                raise RuntimeError("API_KEY is required")
            try:
                from sib_api_v3_sdk import ApiClient, Configuration, TransactionalEmailsApi
            except ImportError as exc:
                raise RuntimeError("sib-api-v3-sdk package required") from exc

            configuration = Configuration()
            configuration.api_key["api-key"] = self._api_key
            api_client = ApiClient(configuration)
            self._transactional_api = TransactionalEmailsApi(api_client)
        return self._transactional_api

    def prepare_email(self, **kwargs):
        """Prepare the SendSmtpEmail object for sending."""
        from sib_api_v3_sdk import SendSmtpEmail, SendSmtpEmailTo, SendSmtpEmailSender, SendSmtpEmailAttachment

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
        email = self.prepare_email(**kwargs)
        api_instance = self._get_transactional_api()
        response = api_instance.send_transac_email(email)
        return {field: str(getattr(response, field)) for field in response.__dict__}


class BrevoSMTPProvider(BrevoProvider):
    """Brevo provider using SMTP."""
    name = "brevo_smtp"
    display_name = "Brevo SMTP"
    required_packages = []
    config_keys = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
        "API_KEY",
        "SMTP_FROM_EMAIL",
    ]
    config_defaults = {
        "SMTP_HOST": "smtp-relay.brevo.com",
        "SMTP_PORT": "587",
        "SMTP_USE_TLS": "true",
        "SMTP_USE_SSL": "false",
    }

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Brevo SMTP provider."""
        super().__init__(**kwargs)
        self._smtp_host = self._get_config_or_env("SMTP_HOST", "smtp-relay.brevo.com")
        self._smtp_port = int(self._get_config_or_env("SMTP_PORT", "587"))
        self._smtp_username = self._get_config_or_env("SMTP_USERNAME")
        self._smtp_password = self._get_config_or_env("SMTP_PASSWORD")
        self._use_tls = self._bool_config("SMTP_USE_TLS", True)
        self._use_ssl = self._bool_config("SMTP_USE_SSL", False)

    def _bool_config(self, key: str, default: bool) -> bool:
        """Convert config value to boolean."""
        value = self._get_config_or_env(key)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value) if value is not None else default

    def prepare_email(self, **kwargs) -> EmailMessage:
        """Prepare the email message for SMTP sending."""
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

        message = EmailMessage()
        message["Subject"] = subject or ""
        
        # Format From header correctly
        if sender_name:
            message["From"] = f"{sender_name} <{sender_email}>"
        else:
            message["From"] = sender_email
        
        message["To"] = recipient_email

        # Set body content - text first, then HTML as alternative
        if body_text:
            message.set_content(body_text, subtype="plain")
        else:
            # Avoid empty payloads
            message.set_content(" ", subtype="plain")
        
        if body and body != body_text:
            message.add_alternative(body, subtype="html")

        reply_to = kwargs.get("reply_to")
        if reply_to:
            message["Reply-To"] = reply_to

        cc = kwargs.get("cc")
        if cc:
            if isinstance(cc, list):
                message["Cc"] = ", ".join(cc)
            else:
                message["Cc"] = cc

        bcc = kwargs.get("bcc")
        if bcc:
            if isinstance(bcc, list):
                message["Bcc"] = ", ".join(bcc)
            else:
                message["Bcc"] = bcc

        for att in self.attachments:
            content = att["content"]
            name = att["name"]
            if isinstance(content, str):
                content = content.encode("utf-8")
            
            # Try to detect MIME type from filename
            mime_type = "application/octet-stream"
            if name:
                if name.lower().endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                elif name.lower().endswith(".png"):
                    mime_type = "image/png"
                elif name.lower().endswith(".pdf"):
                    mime_type = "application/pdf"
                elif name.lower().endswith((".txt", ".text")):
                    mime_type = "text/plain"
                elif name.lower().endswith(".html"):
                    mime_type = "text/html"
            
            maintype, _, subtype = mime_type.partition("/")
            message.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=name,
            )

        return message

    def send_email(self, **kwargs) -> bool:
        """Send email via Brevo SMTP."""
        if not self._smtp_username or not self._smtp_password:
            return False

        try:
            message = self.prepare_email(**kwargs)

            with self._smtp_connection() as smtp:
                smtp.send_message(message)

            return True

        except (OSError, smtplib.SMTPException):
            return False

    @contextmanager
    def _smtp_connection(self):
        """Context manager for SMTP connection."""
        if self._use_ssl:
            smtp = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=10)
        else:
            smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10)
            if self._use_tls:
                smtp.starttls()

        if self._smtp_username and self._smtp_password:
            smtp.login(self._smtp_username, self._smtp_password)

        try:
            yield smtp
        finally:
            try:
                smtp.quit()
            except Exception:
                smtp.close()

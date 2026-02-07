"""Brevo (ex Sendinblue) email provider - API and SMTP modes."""

import base64
import smtplib
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any

from .base import MissiveProviderBase


class BrevoProvider(MissiveProviderBase):
    """Classe de base abstraite pour les providers Brevo."""
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

    def add_attachment_email(self, content: bytes | str, name: str) -> None:
        """Ajoute une pièce jointe à l'email."""
        if isinstance(content, str):
            content = content.encode("utf-8")

        self.attachments.append({"content": content, "name": name})

    def remove_attachment_email(self, name: str) -> None:
        """Retire une pièce jointe de l'email."""
        if not hasattr(self, "attachments"):
            return

        self.attachments = [att for att in self.attachments if att["name"] != name]

    def cancel_email(self) -> bool:
        """Annule l'envoi d'un email (non supporté par Brevo)."""
        return False

    def _update_missive_status(self, status: str, error_message: str | None = None, external_id: str | None = None) -> None:
        """Met à jour le statut de la missive."""
        if self.missive:
            if hasattr(self.missive, "status"):
                self.missive.status = status
            if error_message and hasattr(self.missive, "error_message"):
                self.missive.error_message = error_message
            if external_id and hasattr(self.missive, "external_id"):
                self.missive.external_id = external_id
            if hasattr(self.missive, "provider"):
                self.missive.provider = self.name
            if hasattr(self.missive, "save"):
                self.missive.save()


class BrevoAPIProvider(BrevoProvider):
    """Brevo provider utilisant l'API REST."""
    name = "brevo_api"
    display_name = "Brevo API"
    required_packages = ["sib-api-v3-sdk"]
    config_keys = ["API_KEY"]

    def __init__(self, **kwargs: str | None) -> None:
        """Initialize Brevo API provider."""
        super().__init__(**kwargs)
        self._api_key = self._get_config_or_env("API_KEY")
        self._transactional_api = None
        self._webhooks_api = None

    def _get_transactional_api(self):
        """Retourne l'instance de l'API transactionnelle Brevo."""
        if self._transactional_api is None:
            try:
                from sib_api_v3_sdk import ApiClient, Configuration, TransactionalEmailsApi
            except ImportError as exc:
                raise RuntimeError("sib-api-v3-sdk package required") from exc

            configuration = Configuration()
            configuration.api_key["api-key"] = self._api_key
            api_client = ApiClient(configuration)
            self._transactional_api = TransactionalEmailsApi(api_client)
        return self._transactional_api

    def _get_webhooks_api(self):
        """Retourne l'instance de l'API webhooks Brevo."""
        if self._webhooks_api is None:
            try:
                from sib_api_v3_sdk import ApiClient, Configuration, WebhooksApi
            except ImportError as exc:
                raise RuntimeError("sib-api-v3-sdk package required") from exc

            configuration = Configuration()
            configuration.api_key["api-key"] = self._api_key
            api_client = ApiClient(configuration)
            self._webhooks_api = WebhooksApi(api_client)
        return self._webhooks_api

    def prepare_email(self):
        """Prépare l'objet SendSmtpEmail pour l'envoi."""
        try:
            from sib_api_v3_sdk import SendSmtpEmail, SendSmtpEmailTo, SendSmtpEmailSender, SendSmtpEmailAttachment
        except ImportError as exc:
            raise RuntimeError("sib-api-v3-sdk package required") from exc

        recipient_email = self._get_missive_value("recipient_email")
        sender_email = self._get_missive_value("sender_email")
        sender_name = self._get_missive_value("sender_name")
        subject = self._get_missive_value("subject")
        body = self._get_missive_value("body")
        body_text = self._get_missive_value("body_text")

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

        reply_to = self._get_missive_value("reply_to")
        if reply_to:
            email.reply_to = {"email": reply_to}

        cc = self._get_missive_value("cc")
        if cc:
            if isinstance(cc, list):
                email.cc = [SendSmtpEmailTo(email=email_addr) for email_addr in cc]
            else:
                email.cc = [SendSmtpEmailTo(email=cc)]

        bcc = self._get_missive_value("bcc")
        if bcc:
            if isinstance(bcc, list):
                email.bcc = [SendSmtpEmailTo(email=email_addr) for email_addr in bcc]
            else:
                email.bcc = [SendSmtpEmailTo(email=bcc)]

        if self.attachments:
            email.attachment = [
                SendSmtpEmailAttachment(
                    content=base64.b64encode(att["content"]).decode("utf-8") if isinstance(att["content"], bytes) else att["content"],
                    name=att["name"],
                )
                for att in self.attachments
            ]

        return email

    def send_email(self) -> bool:
        """Envoie l'email via l'API Brevo."""
        if not self._api_key:
            self._update_missive_status("FAILED", "API_KEY is required")
            return False

        try:
            email = self.prepare_email()
            api_instance = self._get_transactional_api()
            result = api_instance.send_transac_email(email)

            message_id = result.message_id if hasattr(result, "message_id") else None
            self._update_missive_status("SENT", external_id=str(message_id) if message_id else None)
            return True

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, "body") and e.body:
                try:
                    import json
                    error_data = json.loads(e.body)
                    error_msg = error_data.get("message", error_msg)
                except Exception:
                    pass
            self._update_missive_status("FAILED", f"Brevo API error: {error_msg}")
            return False

    def set_webhook(self, webhook_url: str, events: list[str] | None = None) -> bool:
        """Configure un webhook pour recevoir les événements Brevo."""
        if not self._api_key:
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
            api_instance = self._get_webhooks_api()
            api_instance.create_webhook(webhook)
            return True

        except Exception:
            return False

    def handle_webhook(self, payload: dict[str, Any], headers: dict[str, str]) -> tuple[bool, str, dict[str, Any] | None]:
        """Traite un webhook Brevo."""
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

    def extract_email_missive_id(self, payload: dict[str, Any]) -> str | None:
        """Extrait l'ID de la missive depuis le webhook Brevo."""
        message_id = payload.get("message-id") or payload.get("messageId")
        return str(message_id) if message_id else None


class BrevoSMTPProvider(BrevoProvider):
    """Brevo provider utilisant SMTP."""
    name = "brevo_smtp"
    display_name = "Brevo SMTP"
    required_packages = []
    config_keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_USE_TLS", "SMTP_USE_SSL"]
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

    def prepare_email(self) -> EmailMessage:
        """Prépare le message email pour l'envoi SMTP."""
        recipient_email = self._get_missive_value("recipient_email")
        sender_email = self._get_missive_value("sender_email")
        sender_name = self._get_missive_value("sender_name")
        subject = self._get_missive_value("subject")
        body = self._get_missive_value("body")
        body_text = self._get_missive_value("body_text")

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

        reply_to = self._get_missive_value("reply_to")
        if reply_to:
            message["Reply-To"] = reply_to

        cc = self._get_missive_value("cc")
        if cc:
            if isinstance(cc, list):
                message["Cc"] = ", ".join(cc)
            else:
                message["Cc"] = cc

        bcc = self._get_missive_value("bcc")
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

    def send_email(self) -> bool:
        """Envoie l'email via SMTP Brevo."""
        if not self._smtp_username or not self._smtp_password:
            self._update_missive_status("FAILED", "SMTP_USERNAME and SMTP_PASSWORD are required")
            return False

        try:
            message = self.prepare_email()

            with self._smtp_connection() as smtp:
                smtp.send_message(message)

            missive_id = getattr(self.missive, "id", "unknown") if self.missive else "unknown"
            self._update_missive_status("SENT", external_id=f"brevo_smtp_{missive_id}")
            return True

        except (OSError, smtplib.SMTPException) as e:
            self._update_missive_status("FAILED", f"Brevo SMTP error: {str(e)}")
            return False

    @contextmanager
    def _smtp_connection(self):
        """Contexte manager pour la connexion SMTP."""
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

    def set_webhook(self, webhook_url: str, events: list[str] | None = None) -> bool:
        """Les webhooks ne sont pas disponibles en mode SMTP."""
        return False

    def handle_webhook(self, payload: dict[str, Any], headers: dict[str, str]) -> tuple[bool, str, dict[str, Any] | None]:
        """Les webhooks ne sont pas disponibles en mode SMTP."""
        return False, "Webhooks not available in SMTP mode", None

    def extract_email_missive_id(self, payload: dict[str, Any]) -> str | None:
        """Les webhooks ne sont pas disponibles en mode SMTP."""
        return None

"""Brevo (ex Sendinblue) provider - Email, SMS, WhatsApp - API v4."""

import contextlib
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pymissive.utils import is_disable_send

from .base import MissiveProviderBase


def _utc_iso_from_timestamp(value) -> str:
    """Convert a Unix timestamp (seconds or milliseconds) to a UTC ISO string."""
    ts = float(value)
    if ts > 1e11:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=dt_timezone.utc).replace(microsecond=0).isoformat()


class BrevoAPIProvider(MissiveProviderBase):
    """Brevo provider - Email, SMS, WhatsApp via API v4."""

    #########################################################
    # Metadata / Configuration
    #########################################################

    name = "brevo"
    display_name = "Brevo"
    description = "Complete CRM platform (Email, SMS, Marketing automation)"
    documentation_url = "https://developers.brevo.com"
    site_url = "https://www.brevo.com"
    brands = ["WhatsApp"]
    required_packages = ["brevo-python>=4.0"]
    config_keys = ["EMAIL_API_KEY", "SMS_API_KEY", "WHATSAPP_API_KEY"]

    fields_associations = {
        "webhook_id": "id",
        "id": "id",
        "url": "url",
        "type": "type",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
        "occurred_at": ["occurred_at", "_date", "date", "trace._date"],
        "event": ["event", "trace.event"],
        "external_id": ["message_id", "messageId", "_message_id", "message-id"],
        "email": ["email", "trace.email"],
        "sender_email": ["_from", "trace._from", "sender_email"],
    }
    events_association = {
        "request": "request",
        "requests": "request",
        "sent": "sent",
        "accepted": "accepted",
        "hardBounce": "hard_bounce",
        "softBounce": "soft_bounce",
        "hardBounces": "hard_bounce",
        "softBounces": "soft_bounce",
        "bounces": "hard_bounce",
        "hard_bounce": "hard_bounce",
        "soft_bounce": "soft_bounce",
        "blocked": "blocked",
        "spam": "spam",
        "delivered": "delivered",
        "click": "clicked",
        "clicks": "clicked",
        "invalid": "invalid",
        "deferred": "deferred",
        "opened": "opened",
        "loadedByProxy": "proxy",
        "proxy_open": "proxy",
        "error": "error",
        "unsubscribed": "unsubscribe",
        "unsubscription": "unsubscribe",
        "rejected": "rejected",
        "skipped": "dropped",
    }
    events_exclude = [
        "requests",
        "hard_bounce",
        "soft_bounce",
        "clicks",
        "hardBounces",
        "softBounces",
    ]

    #########################################################
    # Initialization
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

    #########################################################
    # API clients
    #########################################################

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

    #########################################################
    # Normalization
    #########################################################

    def _recipient(self, event):
        if event.get("email"):
            return {"email": event.get("email")}
        if event.get("phone"):
            return {"phone": event.get("phone")}
        return None

    def get_normalize_recipient(self, data):
        return self._recipient(data)

    def get_normalize_type(self, data: dict[str, Any]) -> str:
        """Return the normalized type of webhook (email, sms, etc.)."""
        if data.get("type") == "transactional":
            return "email"
        if data.get("type") == "marketing":
            return "email_marketing"
        if data.get("type") == "sms":
            return "sms"
        return "unknown"

    def get_normalize_events(self, data):
        if "events" in data:
            return [
                {**event, "recipient": self._recipient(event)}
                for event in data["events"]
            ]
        return None

    #########################################################
    # Helpers
    #########################################################

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

    def get_normalize_occurred_at(self, data: dict[str, Any]) -> str | None:
        """Return occurred_at in UTC.

        Webhook ``date`` is the account timezone (CET/CEST, naive). Retrieve
        ``date`` is UTC (``...Z``). ``ts_event`` / ``ts`` are UTC timestamps.
        Prefer the UTC timestamp so webhook and retrieve upsert the same event.
        """
        nested = data.get("trace") if isinstance(data.get("trace"), dict) else {}
        for source in (data, nested):
            ts = source.get("ts_event")
            if ts is None:
                ts = source.get("ts")
            if ts is not None:
                return _utc_iso_from_timestamp(ts)
        for source in (data, nested):
            for key in ("occurred_at", "_date", "date"):
                value = source.get(key)
                if value:
                    return value
        return None

    def _event_to_payload(self, event: Any) -> dict[str, Any]:
        """Convert event object to dict (Brevo v4 returns Pydantic models)."""
        if isinstance(event, dict):
            data = dict(event)
        elif hasattr(event, "model_dump"):
            data = event.model_dump()
        elif hasattr(event, "dict"):
            data = event.dict()
        else:
            data = {k: v for k, v in vars(event).items() if not k.startswith("_")}
        message_id = data.get("message_id") or data.get("messageId")
        if message_id:
            data["message_id"] = message_id
        phone = data.get("phone") or data.get("phoneNumber")
        if phone:
            data["phone"] = phone
        return data

    def _as_report_date(self, value) -> str:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def _report_date_range(self, start_date, end_date) -> tuple[str, str]:
        start = self._as_report_date(start_date)
        end = self._as_report_date(end_date)
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
        end_d = datetime.strptime(end, "%Y-%m-%d").date()
        if end_d < start_d:
            raise ValueError("end_date must be on or after start_date")
        if (end_d - start_d).days > 90:
            raise ValueError("Brevo event reports cannot exceed 90 days")
        return start, end

    def _event_report_date_chunks(self, start_date, end_date, *, max_days=90):
        start = datetime.strptime(self._as_report_date(start_date), "%Y-%m-%d").date()
        end = datetime.strptime(self._as_report_date(end_date), "%Y-%m-%d").date()
        if end < start:
            start, end = end, start
        current = start
        while current <= end:
            chunk_end = min(current + timedelta(days=max_days), end)
            yield current, chunk_end
            current = chunk_end + timedelta(days=1)

    def _date_from_brevo_message_id(self, external_id):
        """Best-effort date from ids like ``<202605210817.id@smtp-relay.mailin.fr>``."""
        if not external_id:
            return None
        text = str(external_id).lstrip("<")
        if len(text) >= 8 and text[:8].isdigit():
            try:
                return datetime.strptime(text[:8], "%Y%m%d").date()
            except ValueError:
                return None
        return None

    def _response_to_dict(self, response) -> dict[str, Any]:
        """Convert v4 Pydantic response to dict."""
        if isinstance(response, dict):
            return {k: str(v) for k, v in response.items()}
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        else:
            data = dict(vars(response))
        return {k: str(v) for k, v in data.items() if not k.startswith("_")}

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

    #########################################################
    # Webhooks (generic)
    #########################################################

    def retrieve_webhooks(self):
        """Return the Brevo webhooks."""
        client = self._get_webhooks_client()
        response = client.webhooks.get_webhooks()
        webhooks = getattr(response, "webhooks", None)
        if webhooks is None and hasattr(response, "model_dump"):
            webhooks = response.model_dump().get("webhooks", [])
        webhooks = webhooks or []
        return [self._webhook_to_dict(w) for w in webhooks]

    #########################################################
    # Email - Send
    #########################################################

    def delete_blocked_emails(self, kwargs: dict[str, Any]) -> bool:
        with contextlib.suppress(Exception):
            client = self._get_email_client()
            for recipient in kwargs.get("recipients", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(recipient["email"])
            for recipient in kwargs.get("cc", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(recipient["email"])
            for recipient in kwargs.get("bcc", []):
                client.transactional_emails.unblock_or_resubscribe_a_transactional_contact(recipient["email"])
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
        reply_to = kwargs.get("reply_to", {})
        cc = kwargs.get("cc", [])
        bcc = kwargs.get("bcc", [])
        attachments = self._build_attachments(kwargs.get("attachments", []))

        template_id = kwargs.get('template_id')
        if template_id:
            send_kwargs: dict[str, Any] = {
                'template_id': template_id,
                'to': [
                    SendTransacEmailRequestToItem(
                        email=r['email'], name=r.get('name', '')
                    )
                    for r in recipients
                ],
            }
            if sender:
                send_kwargs['sender'] = SendTransacEmailRequestSender(
                    email=sender['email'], name=sender.get('name', '')
                )
            if kwargs.get('params'):
                send_kwargs['params'] = kwargs['params']
        else:
            send_kwargs = {
                'subject': kwargs['subject'],
                'sender': SendTransacEmailRequestSender(
                    email=sender['email'], name=sender.get('name', '')
                ),
                'to': [
                    SendTransacEmailRequestToItem(
                        email=r['email'], name=r.get('name', '')
                    )
                    for r in recipients
                ],
            }
            if kwargs.get('body_rich'):
                send_kwargs['html_content'] = kwargs['body_rich']
            if kwargs.get('body_text'):
                send_kwargs['text_content'] = kwargs['body_text']


        if reply_to:
            send_kwargs["reply_to"] = SendTransacEmailRequestReplyTo(email=reply_to["email"], name=reply_to.get("name", ""))
        if cc:
            send_kwargs["cc"] = [SendTransacEmailRequestCcItem(email=r["email"], name=r.get("name", "")) for r in cc]
        if bcc:
            send_kwargs["bcc"] = [SendTransacEmailRequestBccItem(email=r["email"], name=r.get("name", "")) for r in bcc]
        if attachments:
            send_kwargs["attachment"] = attachments

        if is_disable_send():
            return self._disabled_send_response("send_email", external_id=kwargs.get("external_id"))
        client = self._get_email_client()
        response = client.transactional_emails.send_transac_email(**send_kwargs)
        return self._response_to_dict(response)

    #########################################################
    # Email - Retrieve
    #########################################################

    def retrieve_email(self, **kwargs):
        """Get events for one email via Brevo API v4.

        Without a date window Brevo defaults to the last 30 days, so older
        ``sent`` / ``delivered`` events disappear while a recent ``click``
        still shows. Walk from ``created_at`` (or the message-id date) to
        today in 90-day chunks, filtered by ``message_id``.
        """
        external_id = kwargs.get("external_id")
        start = kwargs.get("created_at") or kwargs.get("start_date")
        if start is None:
            start = self._date_from_brevo_message_id(external_id)
        end = kwargs.get("end_date") or datetime.now(dt_timezone.utc).date()
        if start is None:
            start = end - timedelta(days=90)
        events: list[dict[str, Any]] = []
        for chunk_start, chunk_end in self._event_report_date_chunks(start, end):
            events.extend(
                self._retrieve_email_event_report(
                    self._as_report_date(chunk_start),
                    self._as_report_date(chunk_end),
                    message_id=external_id,
                )
            )
        return {"message_id": external_id, "events": events}

    def retrieve_events(self, start_date, end_date, **kwargs) -> dict[str, Any]:
        """Unaggregated events for a date range (max 90 days).

        Email: GET /v3/smtp/statistics/events (pages of 2500).
        SMS: GET /v3/transactionalSMS/statistics/events (pages of 100).
        Downstream ``handle_events`` update-or-creates each row against the
        matching missive (``message_id`` → ``external_id``).
        """
        missive_type = str(kwargs.get("missive_type") or "email").lower()
        start, end = self._report_date_range(start_date, end_date)
        if missive_type in ("sms", "rcs"):
            events = self._retrieve_sms_event_report(start, end)
        elif missive_type in ("email", "email_marketing", "ere"):
            events = self._retrieve_email_event_report(start, end)
        else:
            raise NotImplementedError(
                f"retrieve_events is not implemented for {missive_type}"
            )
        return {"events": events}

    def _retrieve_email_event_report(
        self,
        start_date: str,
        end_date: str,
        message_id: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._get_email_client()
        limit = 2500
        offset = 0
        events: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
                "offset": offset,
                "sort": "desc",
            }
            if message_id:
                params["message_id"] = message_id
            response = client.transactional_emails.get_email_event_report(**params)
            page = getattr(response, "events", None)
            if page is None and isinstance(response, dict):
                page = response.get("events")
            page = page or []
            events.extend(self._event_to_payload(event) for event in page)
            if len(page) < limit:
                break
            offset += limit
        return events

    def _retrieve_sms_event_report(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        limit = 100
        offset = 0
        events: list[dict[str, Any]] = []
        while True:
            params = urlencode({
                "startDate": start_date,
                "endDate": end_date,
                "limit": limit,
                "offset": offset,
                "sort": "desc",
            })
            req = Request(
                f"https://api.brevo.com/v3/transactionalSMS/statistics/events?{params}",
                headers={"api-key": self._sms_api_key, "Accept": "application/json"},
                method="GET",
            )
            try:
                with urlopen(req) as resp:
                    payload = json.loads(resp.read().decode())
            except HTTPError as e:
                body = e.read().decode() if e.fp else ""
                raise RuntimeError(f"Brevo SMS API error {e.code}: {body}") from e
            page = payload.get("events") or []
            events.extend(self._event_to_payload(event) for event in page)
            if len(page) < limit:
                break
            offset += limit
        return events

    #########################################################
    # Email - Webhooks
    #########################################################

    def create_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Configure a webhook to receive Brevo email events."""
        client = self._get_webhooks_client()
        events = [e for e in self.events_association.keys() if e not in self.events_exclude]
        response = client.webhooks.create_webhook(
            url=webhook_data.get("url"),
            description="Missive webhook email",
            events=events,
            channel="email",
            type="transactional",
        )
        webhook_id = getattr(response, "id", response)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def update_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo email webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def delete_webhook_email(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.delete_webhook(webhook_id)
        return self.get_normalize_webhook_id({"id": webhook_id})

    def _get_webhooks_email(self):
        """Return only transactional email webhooks."""
        webhooks = self.retrieve_webhooks()
        return [
            w for w in webhooks
            if str(w.get("type", "")).lower() == "transactional"
            and str(w.get("channel", "")).lower() in ("email", "")
        ]

    def _retrieve_webhook_email(self, webhook_id: str):
        """Return the Brevo email webhook."""
        webhooks = self._get_webhooks_email()
        return next((w for w in webhooks if str(w.get("id")) == str(webhook_id)), None)

    def handle_webhook_email(self, payload):
        """Handle a Brevo webhook and normalize event type."""
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
            payload = json.loads(payload)
        return payload

    #########################################################
    # Email - Billings
    #########################################################

    def get_billings_email(self, **kwargs: Any) -> dict | list:
        external_id = kwargs.get("external_id")
        emails = []
        for recipient in kwargs.get("recipients") or []:
            email = recipient.get("email") if isinstance(recipient, dict) else None
            if email:
                emails.append(email)
        emails = list(dict.fromkeys(emails))
        return [
            {
                "message_id": external_id,
                "email": email,
                "recipient": {"email": email},
                "billing_amount": 0.0025,
                "estimate_amount": 0.0025,
                "currency": "EUR",
                "invoice": "Email: 1",
            }
            for email in emails
        ]

    #########################################################
    # SMS - Send
    #########################################################

    def send_sms(self, **kwargs) -> dict[str, Any]:
        """Send SMS via Brevo API (direct HTTP, v4 SDK omits content param)."""
        import json as _json
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        sender = kwargs.get("sender", {})
        recipient = str(kwargs["recipients"][0].get("phone", ""))
        sender_name = sender.get("phone") or sender.get("name") or "Missive"
        content = kwargs.get("body_text", "")

        if is_disable_send():
            return self._disabled_send_response("send_sms", external_id=kwargs.get("external_id"))
        body = _json.dumps({"sender": sender_name, "recipient": recipient, "content": content}).encode("utf-8")
        req = Request(
            "https://api.brevo.com/v3/transactionalSMS/sms",
            data=body,
            headers={"api-key": self._sms_api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req) as resp:
                return self._response_to_dict(_json.loads(resp.read().decode()))
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            raise RuntimeError(f"Brevo SMS API error {e.code}: {body}") from e

    #########################################################
    # SMS - Webhooks
    #########################################################

    def create_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
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

    def update_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo SMS webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def delete_webhook_sms(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        client.webhooks.delete_webhook(int(webhook_data.get("id")))
        return self.get_normalize_webhook_id({"id": webhook_data.get("id")})

    def _get_webhooks_sms(self):
        """Return only transactional SMS webhooks."""
        webhooks = self.retrieve_webhooks()
        return [w for w in webhooks if w.get("type") == "transactional" and w.get("channel") == "sms"]

    def _retrieve_webhook_sms(self, webhook_id: str):
        """Return the Brevo SMS webhook."""
        webhooks = self._get_webhooks_sms()
        return next((w for w in webhooks if str(w.get("id")) == str(webhook_id)), None)

    def handle_webhook_sms(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a Brevo webhook and normalize event type."""
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
            payload = json.loads(payload)
        elif isinstance(payload, str):
            payload = json.loads(payload)
        return payload

    #########################################################
    # WhatsApp - Send
    #########################################################

    def send_branded(self, **kwargs) -> dict[str, Any]:
        """Send a branded message via Brevo API (alias for send_whatsapp)."""
        return self.send_whatsapp(**kwargs)

    def send_whatsapp(self, **kwargs) -> dict[str, Any]:
        """Send WhatsApp via Brevo API v4."""
        from brevo.transactional_whats_app import SendWhatsappMessageRequestText

        recipients = [str(r["phone"]) for r in kwargs.get("recipients", [])]
        sender = "+33614397083"
        text = kwargs.get("body_text", "")

        if is_disable_send():
            return self._disabled_send_response("send_whatsapp", external_id=kwargs.get("external_id"))
        request = SendWhatsappMessageRequestText(
            contact_numbers=recipients,
            sender_number=sender,
            text=text,
        )
        client = self._get_whatsapp_client()
        response = client.transactional_whats_app.send_whatsapp_message(request=request)
        return self._response_to_dict(response)

    #########################################################
    # WhatsApp - Webhooks
    #########################################################

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

    def update_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Update a Brevo WhatsApp webhook."""
        client = self._get_webhooks_client()
        webhook_id = int(webhook_data.get("id"))
        client.webhooks.update_webhook(webhook_id, url=webhook_data.get("url"))
        return self.get_normalize_webhook_id({"id": webhook_id})

    def delete_webhook_whatsapp(self, webhook_data: dict[str, Any]) -> bool:
        """Delete a webhook from Brevo."""
        client = self._get_webhooks_client()
        client.webhooks.delete_webhook(int(webhook_data.get("id")))
        return self.get_normalize_webhook_id({"id": webhook_data.get("id")})

    def get_webhooks_whatsapp(self):
        """Return only transactional WhatsApp webhooks."""
        webhooks = self.retrieve_webhooks()
        return [w for w in webhooks if w.get("type") == "transactional" and w.get("channel") == "whatsapp"]

    def get_webhook_whatsapp(self, webhook_id: str):
        """Return the Brevo WhatsApp webhook."""
        webhooks = self.get_webhooks_whatsapp()
        return next((w for w in webhooks if str(w.get("id")) == str(webhook_id)), None)

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
            "occurred_at": payload.get("date"),
            "trace": payload,
        }

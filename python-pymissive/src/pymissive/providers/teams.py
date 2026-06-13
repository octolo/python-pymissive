"""Microsoft Teams provider - send messages via Incoming Webhook.

Unlike Slack/Discord, there is no separate channel ID: the target channel is
chosen when the admin creates the webhook in Teams. The client only stores
the webhook URL (TEAMS_WEBHOOK_URL or per-recipient ``webhook_url``).
"""

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import MissiveProviderBase


class TeamsProvider(MissiveProviderBase):
    """Incoming Webhook only: one URL per channel target, no channel ID field."""

    name = "teams"
    display_name = "Microsoft Teams"
    description = (
        "Microsoft Teams notifications via Incoming Webhook URL "
        "(no channel ID — the URL is tied to the channel when created in Teams)"
    )
    brands = ["teams"]
    config_keys = ["TEAMS_WEBHOOK_URL"]
    site_url = "https://www.microsoft.com/microsoft-teams"
    documentation_url = (
        "https://learn.microsoft.com/microsoftteams/platform/webhooks-and-connectors/"
        "how-to/add-incoming-webhook"
    )

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self._default_webhook_url = self._get_config_or_env("TEAMS_WEBHOOK_URL")

    def _resolve_webhook_url(self, **kwargs: Any) -> str:
        """Resolve webhook URL from kwargs, recipients, or TEAMS_WEBHOOK_URL."""
        if kwargs.get("webhook_url"):
            return str(kwargs["webhook_url"])

        recipients = kwargs.get("recipients", [])
        if recipients:
            recipient = recipients[0] or {}
            for key in ("webhook_url", "url", "web_hook_url", "incoming_webhook_url"):
                if recipient.get(key):
                    return str(recipient[key])

        if self._default_webhook_url:
            return str(self._default_webhook_url)

        raise ValueError(
            "Teams webhook_url is required (kwargs, recipients, or TEAMS_WEBHOOK_URL)",
        )

    def send_branded(self, **kwargs: Any) -> dict[str, Any]:
        """Post a message to a Teams channel using an Incoming Webhook."""
        webhook_url = self._resolve_webhook_url(**kwargs)
        subject = (kwargs.get("subject") or "").strip()
        text = kwargs.get("body_text") or kwargs.get("body_rich") or kwargs.get("subject") or ""
        text = str(text).strip()
        if not text:
            raise ValueError("Teams message text is required (body_text, body_rich, or subject)")

        # Simple text works on all Teams webhook versions; MessageCard adds a title when subject differs.
        if subject and subject != text:
            payload_obj: dict[str, Any] = {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": subject[:160],
                "themeColor": "0078D4",
                "title": subject,
                "text": text,
            }
        else:
            payload_obj = {"text": text}

        payload = json.dumps(payload_obj).encode("utf-8")
        request = Request(
            url=webhook_url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with urlopen(request) as response:
                body = response.read().decode("utf-8")
                message_id = body.strip() or "sent"
                # No channel_id (unlike Slack/Discord): destination is the webhook URL.
                return {
                    "id": message_id,
                    "channel_id": "",
                    "status": "sent",
                }
        except HTTPError as error:
            err_body = error.read().decode("utf-8") if error.fp else ""
            raise RuntimeError(f"Teams webhook error {error.code}: {err_body}") from error

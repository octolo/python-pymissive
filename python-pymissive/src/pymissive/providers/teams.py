"""Microsoft Teams provider - send messages via Incoming Webhook.

Unlike Slack/Discord, there is no separate channel ID: the target channel is
chosen when the admin creates the webhook in Teams. The client only stores
the webhook URL (TEAMS_WEBHOOK_URL or per-recipient ``webhook_url``).
"""

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pymissive.utils import HTTP_TIMEOUT, require_https_url

from .base import MissiveProviderBase


_WEBHOOK_HOSTS = ("outlook.office.com", "outlook.office365.com")
_WEBHOOK_HOST_SUFFIXES = (".webhook.office.com", ".logic.azure.com", ".environment.api.powerplatform.com")


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_WEBHOOK_OPENER = build_opener(_NoRedirects)


def _require_teams_webhook_url(url: str) -> str:
    url = require_https_url(url)
    hostname = urlparse(url).hostname or ""
    if hostname not in _WEBHOOK_HOSTS and not hostname.endswith(_WEBHOOK_HOST_SUFFIXES):
        raise ValueError("Teams webhook URL must use a Microsoft Teams webhook host")
    return url


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
        "https://learn.microsoft.com/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook"
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

    @staticmethod
    def _build_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
        subject = (kwargs.get("subject") or "").strip()
        text = kwargs.get("body_text") or kwargs.get("body_rich") or kwargs.get("subject") or ""
        text = str(text).strip()
        if not text:
            raise ValueError("Teams message text is required (body_text, body_rich, or subject)")

        if subject and subject != text:
            return {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": subject[:160],
                "themeColor": "0078D4",
                "title": subject,
                "text": text,
            }
        return {"text": text}

    @staticmethod
    def _post_webhook(webhook_url: str, payload_obj: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            url=webhook_url,
            data=json.dumps(payload_obj).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with _WEBHOOK_OPENER.open(request, timeout=HTTP_TIMEOUT) as response:  # nosec B310
                body = response.read().decode("utf-8")
                message_id = body.strip() or "sent"
                return {
                    "id": message_id,
                    "channel_id": "",
                    "status": "sent",
                }
        except HTTPError as error:
            err_body = error.read().decode("utf-8") if error.fp else ""
            raise RuntimeError(f"Teams webhook error {error.code}: {err_body}") from error

    def send_branded(self, brand_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Post a message to a Teams channel using an Incoming Webhook."""
        webhook_url = _require_teams_webhook_url(self._resolve_webhook_url(**kwargs))
        return self._post_webhook(webhook_url, self._build_payload(kwargs))

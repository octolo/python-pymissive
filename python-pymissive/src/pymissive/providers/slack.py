"""Slack provider - send messages to channels."""

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import MissiveProviderBase

class SlackProvider(MissiveProviderBase):
    """Slack provider for branded messages in channels."""

    name = "slack"
    display_name = "Slack"
    description = "Professional team collaboration messaging"
    brands = ["slack"]
    config_keys = ["SLACK_BOT_TOKEN", "SLACK_CHANNEL_ID"]

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self._bot_token = self._get_config_or_env("SLACK_BOT_TOKEN")
        self._default_channel_id = self._get_config_or_env("SLACK_CHANNEL_ID")

    def _resolve_channel_id(self, **kwargs: Any) -> str:
        """Resolve channel id from kwargs recipients or provider config."""
        if kwargs.get("channel_id"):
            return str(kwargs["channel_id"])

        recipients = kwargs.get("recipients", [])
        if recipients:
            recipient = recipients[0] or {}
            for key in ("channel_id", "id", "channel"):
                if recipient.get(key):
                    return str(recipient[key])

        if self._default_channel_id:
            return str(self._default_channel_id)

        raise ValueError("Slack channel_id is required (kwargs, recipients, or SLACK_CHANNEL_ID)")

    def send_branded(self, **kwargs: Any) -> dict[str, Any]:
        """Send a branded message to a Slack channel."""
        channel_id = self._resolve_channel_id(**kwargs)
        text = kwargs.get("body_text") or kwargs.get("body_rich") or kwargs.get("subject") or ""
        if not text:
            raise ValueError("Slack text is required (body_text, body_rich, or subject)")

        payload = json.dumps({"channel": channel_id, "text": str(text)}).encode("utf-8")
        request = Request(
            url="https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )

        try:
            with urlopen(request) as response:
                data = json.loads(response.read().decode("utf-8"))
                if not data.get("ok"):
                    raise RuntimeError(f"Slack API error: {data.get('error', 'unknown_error')}")
                return {
                    "id": str(data.get("ts", "")),
                    "channel_id": str(data.get("channel", channel_id)),
                    "status": "sent",
                }
        except HTTPError as error:
            body = error.read().decode("utf-8") if error.fp else ""
            raise RuntimeError(f"Slack API error {error.code}: {body}") from error

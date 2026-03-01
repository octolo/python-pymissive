"""Slack provider for channel and direct messaging."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class SlackProvider(BaseProvider):
    """Slack provider."""

    name = "slack"
    display_name = "Slack"
    supported_types = ["BRANDED"]
    services = ["slack", "messaging"]
    brands = ["slack"]
    config_keys = ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"]
    required_packages = ["slack-sdk"]
    site_url = "https://slack.com/"
    status_url = "https://status.slack.com/"
    documentation_url = "https://api.slack.com/"
    description_text = "Professional team collaboration messaging"
    # Geographic scope
    branded_geo = "*"

    def validate(self) -> tuple[bool, str]:
        """Validates recipient has Slack user_id or channel_id."""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient:
            return False, "Recipient not defined"

        metadata = getattr(recipient, "metadata", None) or {}
        user_id = metadata.get("slack_user_id")
        channel_id = metadata.get("slack_channel_id")

        if not user_id and not channel_id:
            return (
                False,
                "Recipient must have slack_user_id or slack_channel_id in metadata",
            )

        return True, ""

    def send_slack(self) -> bool:
        """Sends Slack message via Web API."""
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        # from slack_sdk import WebClient
        #
        # client = WebClient(token=self._config.get("SLACK_BOT_TOKEN"))
        # response = client.chat_postMessage(
        #     channel=channel_id or user_id,
        #     text=self.missive.body_text,
        #     blocks=[...]  # For rich formatting
        # )

        external_id = f"slack_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """Checks if message was read (requires Events API)."""
        # TODO: Implement via Slack Events API
        return None


__all__ = ["SlackProvider"]

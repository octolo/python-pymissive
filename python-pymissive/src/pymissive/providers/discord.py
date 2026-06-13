"""Discord provider - send messages to channels."""

import asyncio
from typing import Any

from .base import MissiveProviderBase


class DiscordProvider(MissiveProviderBase):
    """Discord provider for branded messages in channels."""

    name = "discord"
    display_name = "Discord"
    description = "Community communication platform with channels"
    brands = ["discord"]
    config_keys = ["DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"]
    required_packages = ["discord.py"]
    site_url = "https://discord.com"
    documentation_url = "https://discord.com/developers/docs"

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self._bot_token = self._get_config_or_env("DISCORD_BOT_TOKEN")
        self._default_channel_id = self._get_config_or_env("DISCORD_CHANNEL_ID")


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

        raise ValueError("Discord channel_id is required (kwargs, recipients, or DISCORD_CHANNEL_ID)")

    def send_branded(self, **kwargs: Any) -> dict[str, Any]:
        """Send a branded message to a Discord channel."""
        channel_id = self._resolve_channel_id(**kwargs)
        content = kwargs.get("body_text") or kwargs.get("body_rich") or kwargs.get("subject") or ""
        if not content:
            raise ValueError("Discord content is required (body_text, body_rich, or subject)")

        import discord

        async def _send_message() -> dict[str, Any]:
            intents = discord.Intents.none()
            client = discord.Client(intents=intents)
            send_result: dict[str, Any] = {}

            @client.event
            async def on_ready() -> None:
                try:
                    channel = client.get_channel(int(channel_id))
                    if channel is None:
                        channel = await client.fetch_channel(int(channel_id))
                    message = await channel.send(str(content))
                    send_result.update(
                        {
                            "id": str(message.id),
                            "channel_id": str(channel.id),
                            "status": "sent",
                        }
                    )
                finally:
                    await client.close()

            await client.start(self._bot_token)
            if not send_result:
                raise RuntimeError("Discord send failed: no message returned")
            return send_result

        try:
            return asyncio.run(_send_message())
        except Exception as error:
            raise RuntimeError(f"Discord SDK error: {error}") from error

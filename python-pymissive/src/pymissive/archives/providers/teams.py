"""Microsoft Teams provider."""

from __future__ import annotations

from typing import Optional

from ..status import MissiveStatus
from .base import BaseProvider


class TeamsProvider(BaseProvider):
    """
    Microsoft Teams provider.

    Required configuration:
        TEAMS_CLIENT_ID: Azure AD app Client ID
        TEAMS_CLIENT_SECRET: Client Secret
        TEAMS_TENANT_ID: Tenant ID

    Recipient must have:
    - A Microsoft user_id (in metadata.teams_user_id)
    - OR a Teams channel_id (in metadata.teams_channel_id)
    """

    name = "teams"
    display_name = "Microsoft Teams"
    supported_types = ["BRANDED"]  # Uses generic BRANDED type
    services = ["teams", "messaging"]
    brands = ["teams"]  # Microsoft Teams only
    config_keys = ["TEAMS_CLIENT_ID", "TEAMS_CLIENT_SECRET", "TEAMS_TENANT_ID"]
    required_packages = ["msgraph-core", "msal"]
    site_url = "https://www.microsoft.com/microsoft-teams/"
    status_url = "https://status.azure.com/en-us/status"
    documentation_url = "https://learn.microsoft.com/en-us/microsoftteams/"
    description_text = "Microsoft Teams - Enterprise communication (Microsoft 365)"
    # Geographic scope
    branded_geo = "*"

    def validate(self) -> tuple[bool, str]:
        """Validate that the recipient has a Teams user_id or channel_id"""
        if not self.missive:
            return False, "Missive not defined"

        recipient = getattr(self.missive, "recipient", None)
        if not recipient:
            return False, "Recipient not defined"

        metadata = getattr(recipient, "metadata", None) or {}
        user_id = metadata.get("teams_user_id")
        channel_id = metadata.get("teams_channel_id")

        if not user_id and not channel_id:
            return (
                False,
                "Recipient must have a teams_user_id or teams_channel_id in metadata",
            )

        return True, ""

    def send_teams(self) -> bool:
        """
        Send a Teams message via Microsoft Graph API.

        TODO: Implement actual sending via:
        POST https://graph.microsoft.com/v1.0/chats/{chat-id}/messages
        """
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        # TODO: Implement actual sending
        # 1. Get an OAuth access token
        # 2. Send the message via Graph API
        # 3. Handle adaptive cards for rich content

        external_id = f"teams_sim_{getattr(self.missive, 'id', 'unknown')}"
        self._update_status(
            MissiveStatus.SENT,
            external_id=external_id,
        )

        return True

    def check_status(self, external_id: Optional[str] = None) -> Optional[str]:
        """Check status via Graph API"""
        # TODO: Implement via Microsoft Graph API
        return None


__all__ = ["TeamsProvider"]

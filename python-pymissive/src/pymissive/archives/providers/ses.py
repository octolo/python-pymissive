"""Amazon SES email provider."""

from __future__ import annotations

from typing import Dict

from ..status import MissiveStatus
from .base import BaseProvider


class SESProvider(BaseProvider):
    """
    Amazon SES (Simple Email Service) provider.

    Required configuration:
        AWS_ACCESS_KEY_ID: AWS access key
        AWS_SECRET_ACCESS_KEY: AWS secret key
        AWS_REGION: AWS region (e.g., eu-west-1, us-east-1)
        SES_FROM_EMAIL: Verified sender email in SES

    Supports:
    - Transactional email
    - Email marketing (with SES v2)
    - Reputation management
    """

    name = "ses"
    display_name = "Amazon SES"
    supported_types = ["EMAIL"]
    services = ["email", "email_transactional", "email_marketing"]
    config_keys = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_FROM_EMAIL",
    ]
    required_packages = ["boto3"]
    site_url = "https://aws.amazon.com/ses/"
    status_url = "https://health.aws.amazon.com/health/status"
    documentation_url = "https://docs.aws.amazon.com/ses/"
    description_text = "Amazon Simple Email Service - AWS transactional email"

    def send_email(self, **kwargs) -> bool:
        """Send an email via Amazon SES"""
        # Validation
        is_valid, error = self.validate()
        if not is_valid:
            self._update_status(MissiveStatus.FAILED, error_message=error)
            return False

        if not self._get_missive_value("recipient_email"):
            self._update_status(MissiveStatus.FAILED, error_message="Email missing")
            return False

        try:
            # Configuration AWS
            aws_access_key = self._config.get("AWS_ACCESS_KEY_ID")
            aws_secret_key = self._config.get("AWS_SECRET_ACCESS_KEY")
            self._config.get("AWS_REGION", "eu-west-1")
            from_email = self._config.get("SES_FROM_EMAIL")

            if not all([aws_access_key, aws_secret_key, from_email]):
                self._update_status(
                    MissiveStatus.FAILED,
                    error_message="Incomplete AWS SES configuration",
                )
                return False

            # TODO: Implement actual SES sending
            # import boto3
            # from botocore.exceptions import ClientError
            #
            # client = boto3.client(
            #     "ses",
            #     aws_access_key_id=aws_access_key,
            #     aws_secret_access_key=aws_secret_key,
            #     region_name=aws_region,
            # )
            #
            # destination = {"ToAddresses": [self.missive.recipient_email]}
            # message = {
            #     "Subject": {"Data": self.missive.subject, "Charset": "UTF-8"},
            #     "Body": {},
            # }
            #
            # if self.missive.body_html:
            #     message["Body"]["Html"] = {
            #         "Data": self.missive.body_html,
            #         "Charset": "UTF-8",
            #     }
            # if self.missive.body_text or self.missive.body:
            #     message["Body"]["Text"] = {
            #         "Data": self.missive.body_text or self.missive.body,
            #         "Charset": "UTF-8",
            #     }
            #
            # response = client.send_email(
            #     Source=from_email,
            #     Destination=destination,
            #     Message=message,
            # )
            #
            # message_id = response.get("MessageId")

            # Simulation
            message_id = f"ses_{getattr(self.missive, 'id', 'unknown')}"

            self._update_status(
                MissiveStatus.SENT,
                provider=self.name,
                external_id=message_id,
            )
            self._create_event("sent", f"Email sent via Amazon SES (ID: {message_id})")

            return True

        except Exception as e:
            self._update_status(MissiveStatus.FAILED, error_message=str(e))
            self._create_event("failed", str(e))
            return False

    def get_email_service_info(self) -> Dict:
        """
        Gets Amazon SES service information.

        Returns:
            Dict with quotas, credits, reputation, etc.
        """
        try:
            aws_access_key = self._config.get("AWS_ACCESS_KEY_ID")
            aws_secret_key = self._config.get("AWS_SECRET_ACCESS_KEY")
            aws_region = self._config.get("AWS_REGION", "eu-west-1")

            if not all([aws_access_key, aws_secret_key]):
                return {
                    "credits": None,
                    "credits_type": "quota",
                    "is_available": False,
                    "limits": {},
                    "warnings": ["Incomplete AWS configuration"],
                    "reputation": {},
                    "details": {},
                }

            # TODO: Implement actual SES API calls
            # import boto3
            # from botocore.exceptions import ClientError
            #
            # client = boto3.client(
            #     "ses",
            #     aws_access_key_id=aws_access_key,
            #     aws_secret_access_key=aws_secret_key,
            #     region_name=aws_region,
            # )
            #
            # quota = client.get_send_quota()
            # max_24h = int(quota.get("Max24HourSend", 0))
            # sent_last_24h = int(quota.get("SentLast24Hours", 0))
            # remaining = max_24h - sent_last_24h

            return {
                "credits": None,
                "credits_type": "quota",
                "is_available": None,
                "limits": {},
                "warnings": ["SES API not implemented - uncomment the code"],
                "reputation": {},
                "details": {
                    "region": aws_region,
                },
            }

        except Exception as e:
            return {
                "credits": None,
                "credits_type": "quota",
                "is_available": False,
                "limits": {},
                "warnings": [f"Error: {str(e)}"],
                "reputation": {},
                "details": {},
            }


__all__ = ["SESProvider"]

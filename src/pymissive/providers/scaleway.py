"""Scaleway Transactional Email provider."""

import json
from functools import cached_property
from typing import Any

import requests

from .base import MissiveProviderBase


class ScalewayProvider(MissiveProviderBase):
    name = "scaleway"
    display_name = "Scaleway"
    description = "Scaleway messaging and communication services"
    required_packages = ["requests", "boto3"]
    documentation_url = "https://www.scaleway.com/en/docs/managed-services/transactional-email/"
    site_url = "https://www.scaleway.com"
    config_keys = [
        "ACCESS_KEY",
        "SECRET_ACCESS_KEY",
        "REGION",
        "PROJECT_ID",
        "BASE_URL",
        "WEBHOOK_ID",
        "DOMAIN_ID",
        "SNS_ACCESS_KEY",
        "SNS_SECRET_KEY",
        "WEBHOOK_URL",
    ]
    config_defaults = {
        "BASE_URL": "https://api.scaleway.com",
        "REGION": "fr-par",
        "WEBHOOK_ID": "default",
    }
    ENDPOINTS = {
        "email": "{base_url}/transactional-email/v1alpha1/regions/{region}/emails",
        "webhooks": "{base_url}/transactional-email/v1alpha1/regions/{region}/webhooks",
        "domains": "{base_url}/transactional-email/v1alpha1/regions/{region}/domains",
        "activate_sns": "{base_url}/mnq/v1beta1/regions/{region}/activate-sns",
        "sns_info": "{base_url}/mnq/v1beta1/regions/{region}/sns-info",
        "sns_credentials": "{base_url}/mnq/v1beta1/regions/{region}/sns-credentials",
    }
    EVENT_TYPES = [
        "email_sent", "email_delivered", "email_queued", "email_dropped",
        "email_deferred", "email_spam", "email_mailbox_not_found", "email_blocklisted",
    ]
    events_association = {
        "unknown_type": "unknown",
        "email_queued": "queued",
        "email_delivered": "delivered",
        "email_dropped": "dropped",
        "email_deferred": "deferred",
        "email_spam": "spam",
        "email_mailbox_not_found": "mailbox_not_found",
        "email_blocklisted": "blocklisted",
    }

    def __init__(self, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        base = self._get_config_or_env("BASE_URL", "https://api.scaleway.com")
        self._base_url = base.rstrip("/")
        self._access_key = self._get_config_or_env("ACCESS_KEY")
        self._secret_key = self._get_config_or_env("SECRET_ACCESS_KEY")
        self._region = self._get_config_or_env("REGION", "fr-par")
        self._project_id = self._get_config_or_env("PROJECT_ID")
        self._email_data: dict[str, Any] = {}

    def _get_mnq_api(self):
        """Return MnqV1Beta1SnsAPI if scaleway SDK is available and configured. Else None."""
        if not self._access_key or not self._secret_key:
            return None
        try:
            from scaleway import Client
            from scaleway.mnq.v1beta1 import MnqV1Beta1SnsAPI

            client = Client(
                access_key=self._access_key,
                secret_key=self._secret_key,
                default_project_id=self._project_id or "",
                default_region=self._region,
            )
            return MnqV1Beta1SnsAPI(client)
        except ImportError:
            return None

    #########################################################
    # Helpers
    #########################################################

    def _get_headers(self) -> dict[str, str]:
        """Generate standard headers."""
        return {
            "X-Auth-Token": self._secret_key,
            "Content-Type": "application/json",
        }

    def _build_url(self, url_key: str) -> str:
        """Build URL from endpoint key."""
        return self.ENDPOINTS[url_key].format(base_url=self._base_url, region=self._region)

    def get_external_id_email(self, response: dict[str, Any]) -> str:
        """Get external email ID."""
        message_id = None
        if "email_headers" in response:
            email_headers = response.get("email_headers")
            keys = ["X-Scw-Tem-Message-Id",]
            message_id = next((header.get("value") for header in email_headers if header.get("key") in keys), None)
        if not message_id:
            message_id = response.get("emails")[0].get("message_id")
        return message_id

    def get_subscription_id(self, sub_arn: str) -> str:
        return sub_arn.split(":")[-1]

    def get_normalize_id(self, data: dict[str, Any]) -> str:
        """Get normalized ID."""
        return self.get_subscription_id(data.get("sub_id"))

    def get_normalize_webhook_id(self, data: dict[str, Any]) -> str:
        """Get normalized webhook ID."""
        wbh_id = data.get('id')
        sub_id = self.get_subscription_id(data.get('sub_id'))
        return f"{self.name}-{wbh_id}_{sub_id}"

    def get_domains(self):
        """Get domains."""
        url = self.ENDPOINTS["domains"].format(base_url=self._base_url, region=self._region)
        response = requests.get(
            url,
            headers=self._get_headers(),
            params={"project_id": self._project_id}, timeout=30
        )
        response.raise_for_status()
        return response.json()

    #########################################################
    # Email sending
    #########################################################

    def _prepare_email(self, **kwargs):
        """Prepare email data for Scaleway API."""
        if not self._project_id:
            raise ValueError("PROJECT_ID is required for Scaleway transactional email")
        self._email_data = {
            "subject": kwargs["subject"],
            "project_id": self._project_id,
            "additional_headers": [],
        }
        self._add_sender(kwargs["sender"])
        self._add_content(kwargs)
        self._add_reply_to(kwargs)
        self._add_recipients(kwargs.get("recipients", []))
        self._add_bcc_or_cc(kwargs.get("bcc", []), "bcc")
        self._add_bcc_or_cc(kwargs.get("cc", []), "cc")
        self._add_attachments_email(kwargs.get("attachments", []))
        return self._email_data

    def _add_sender(self, sender):
        self._email_data["from"] = {
            "email": sender["email"],
            "name": sender.get("name") or "",
        }

    def _add_content(self, kwargs):
        if kwargs.get("body"):
            self._email_data["html"] = kwargs["body"]
        if kwargs.get("body_text"):
            self._email_data["text"] = kwargs["body_text"]
        if "html" not in self._email_data and "text" not in self._email_data:
            self._email_data["text"] = ""

    def _add_reply_to(self, kwargs):
        reply_to = kwargs.get("reply_to")
        if reply_to:
            value = reply_to["email"] if isinstance(reply_to, dict) else reply_to
            self._email_data["additional_headers"].append({
                "key": "Reply-To",
                "value": value,
            })

    def _add_recipients(self, recipients):
        self._email_data["to"] = [
            {"email": recipient["email"], "name": recipient.get("name", "")}
            for recipient in recipients
        ]

    def _add_bcc_or_cc(self, recipients, key):
        if not recipients or key not in ["cc", "bcc"]:
            return
        self._email_data[key] = [
            {"email": recipient["email"], "name": recipient.get("name", "")}
            for recipient in recipients
        ]

    def _add_attachments_email(self, attachments):
        if not attachments:
            return
        self._email_data["attachments"] = [
            {
                "name": att["name"],
                "type": att.get("type") or self._guess_content_type(att["name"]),
                "content": self._to_base64(att["content"]),
            }
            for att in attachments
        ]

    def send_email(self, **kwargs: Any) -> bool:
        """Send email via Scaleway."""
        self._prepare_email(**kwargs)
        response = requests.post(
            self._build_url("email"),
            headers=self._get_headers(),
            json=self._email_data,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    #########################################################
    # Webhooks
    #########################################################

    def insert_type_and_url_webhooks(self, sns, webhooks: list[dict[str, Any]]):
        """Insert type and url in webhooks."""
        for wbh in webhooks:
            wbh["type"] = wbh["name"].split("-")[-1]
            topic_arn = wbh.get("sns_arn")
            wbh["url"] = self.get_subscription(sns, topic_arn).get("Endpoint")
        return webhooks

    def get_webhook(self, domain_id: str, sns_arn: str):
        """Get a webhook."""
        webhooks = self.get_webhooks()
        for wbh in webhooks:
            if wbh.get("domain_id") == domain_id and wbh.get("sns_arn") == sns_arn:
                return wbh
        return None

    def get_or_create_webhook(self, domain_id: str, sns_arn: str):
        webhook = self.get_webhook(domain_id, sns_arn)
        if webhook:
            return webhook
        url = self.ENDPOINTS["webhooks"].format(base_url=self._base_url, region=self._region)
        response = requests.post(
            url,
            headers=self._get_headers(),
            json={
                "project_id": self._project_id,
                "domain_id": domain_id,
                "name": "missive-webhook-email",
                "sns_arn": sns_arn,
                "event_types": self.EVENT_TYPES
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()        

    def get_webhooks(self):
        """Get all webhooks."""
        url = self.ENDPOINTS["webhooks"].format(base_url=self._base_url, region=self._region)
        response = requests.get(
            url,
            headers=self._get_headers(),
            params={"project_id": self._project_id},
            timeout=30
        )
        response.raise_for_status()
        response = response.json()
        response = response.get("webhooks", [])
        response = [wbh for wbh in response if wbh.get("project_id") == self._project_id]
        return self.merge_subscriptions_url(response)

    def get_webhook_email(self, webhook_id: str):
        """Get a webhook."""
        for wbh in self.get_webhooks():
            if "missive-webhook-email" in wbh.get("sns_arn"):
                return wbh
        return None

    def set_webhook_email(self, webhook_data: dict[str, Any]):
        """Set a webhook email."""
        sns = self.sns_client_email
        topic = self.get_or_create_topic(sns, name="missive-webhook-email")
        topic_arn = topic.get("TopicArn")
        subscription = self.get_or_create_subscription(sns, topic_arn, webhook_data.get("url"))
        domains = self.get_domains()
        domain_id = domains.get("domains", [])[0].get("id")
        webhook = self.get_or_create_webhook(domain_id, topic_arn)
        return self.get_normalize_webhook_id({
            "id": webhook.get("id"), 
            "sub_id": subscription.get("SubscriptionArn")
        })

    def delete_webhook_email(self, webhook_data: dict[str, Any]):
        """Delete a webhook email."""
        webhook_id = webhook_data.get("id")
        webhook_url = webhook_data.get("url")
        webhook_type = webhook_data.get("type")
        sns = getattr(self, f"sns_client_{webhook_type}")
        webhook = getattr(self, f"get_webhook_{webhook_type}")(webhook_id)
        self.delete_subscription(sns, webhook, webhook_url)

    def _handle_webhook_email_confirm(self, payload: dict[str, Any]) -> None:
        """Handle a webhook confirm email."""
        subscription_url = payload.get("SubscribeURL")
        requests.get(subscription_url, timeout=30)
        return None

    def _handle_webhook_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a webhook email notification (SNS Notification with Message as JSON)."""
        event = payload.get("type", "unknown")
        return {
            "recipient": payload.get("email_to"),
            "external_id": self.get_external_id_email(payload),
            "event": self.events_association.get(event, "unknown"),
            "description": payload.get("email_response_message"),
            "occurred_at": payload.get("created_at") or payload.get("email_sent_at"),
            "trace": payload,
        }

    def handle_webhook_email(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a webhook email."""
        payload = payload.decode("utf-8")
        payload = json.loads(payload)
        if payload.get("Type") == "SubscriptionConfirmation":
            return self._handle_webhook_email_confirm(payload)
        if payload.get("Type") == "Notification":
            message = payload.get("Message")
            if isinstance(message, str):
                message = json.loads(message)
            return self._handle_webhook_email(message)
        return None

    #########################################################
    # Topics / Events
    #########################################################

    def get_or_create_topic(self, sns, name: str):
        """Get a topic."""
        paginator = sns.get_paginator("list_topics")
        for page in paginator.paginate():
            for topic in page.get("Topics", []):
                arn = topic.get("TopicArn")
                if arn.endswith(f":{name}"):
                    return topic
        return sns.create_topic(Name=name)

    #########################################################
    # Sns
    #########################################################

    def get_sns_info(self):
        """Get SNS info."""
        url = self.ENDPOINTS["sns_info"].format(base_url=self._base_url, region=self._region)
        response = requests.get(
            url,
            headers=self._get_headers(),
            params={"project_id": self._project_id},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def is_sns_active(self):
        """Check if SNS is active."""
        url = self.ENDPOINTS["activate_sns"].format(base_url=self._base_url, region=self._region)
        response = requests.post(
            url,
            headers=self._get_headers(),
            json={"project_id": self._project_id}, 
            timeout=30
        )
        if response.status_code == 409:
            return self.get_sns_info()
        response.raise_for_status()
        return response.json()

    def log_sns_credentials(self, access_key: str, secret_key: str):
        scaleway_sns_save_method = self._get_config_or_env("SCALEWAY_SNS_SAVE_METHOD")
        separator = "--------------- sns credentials ---------------"
        if scaleway_sns_save_method == "logger":
            import logging
            logger = logging.getLogger(__name__)
            logger.info(separator)
            logger.info("SNS_ACCESS_KEY =", access_key)
            logger.info("SNS_SECRET_KEY =", secret_key)
            logger.info(separator)
        elif scaleway_sns_save_method == "print":
            print(separator)
            print("SNS_ACCESS_KEY =", access_key)
            print("SNS_SECRET_KEY =", secret_key)
            print(separator)
        else:
            filename = f"sns_credentials_{self._project_id}.txt"
            print(separator)
            print(f"Saving SNS credentials to {filename}")
            print(separator)
            with open(filename, "a") as f:
                f.write("SNS_ACCESS_KEY = " + access_key + "\n")
                f.write("SNS_SECRET_KEY = " + secret_key + "\n")

    def create_sns_credentials(self, name: str = "missive-webhook-email"):
        """Create SNS credentials."""
        url = self.ENDPOINTS["sns_credentials"].format(base_url=self._base_url, region=self._region)
        response = requests.post(
            url,
            headers=self._get_headers(),
            json={
                "project_id": self._project_id,
                "name": name,
                "permissions": {
                    "can_publish": True,
                    "can_receive": True,
                    "can_manage": True
                }
            },
            timeout=30,
        )
        response.raise_for_status()
        response = response.json()
        self._tmp_sns_access_key = response.get("access_key")
        self._tmp_sns_secret_key = response.get("secret_key")
        self.log_sns_credentials(response.get("access_key"), response.get("secret_key"))
        return response
    
    def sns_client(self, name: str = "missive-webhook-email"):
        """Get SNS client."""
        import boto3
        from botocore.config import Config
        sns_info = self.is_sns_active()
        if not hasattr(self, "_tmp_sns_access_key"):
            self._tmp_sns_access_key = self._get_config_or_env("SNS_ACCESS_KEY")
        if not hasattr(self, "_tmp_sns_secret_key") or not self._tmp_sns_secret_key:
            self._tmp_sns_secret_key = self._get_config_or_env("SNS_SECRET_KEY")
        if not self._tmp_sns_access_key or not self._tmp_sns_secret_key:
            self.create_sns_credentials(name=name)
        return boto3.client(
            "sns",
            endpoint_url=sns_info.get("sns_endpoint_url"),
            aws_access_key_id=self._tmp_sns_access_key,
            aws_secret_access_key=self._tmp_sns_secret_key,
            region_name=self._region,
            config=Config(signature_version="s3v4"),
        )

    @cached_property
    def sns_client_email(self):
        """Get SNS client."""
        return self.sns_client(name="missive-webhook-email")

    #########################################################
    # Subscriptions
    #########################################################

    def get_or_create_subscription(self, sns, topic_arn: str, webhook_url: str):
        """Create a subscription."""        
        subscription = self.get_subscription(sns, topic_arn, webhook_url)
        if not subscription:
            return sns.subscribe(TopicArn=topic_arn, Protocol="https", Endpoint=webhook_url)
        return subscription

    def merge_subscriptions_url(self, webhooks: list[dict[str, Any]]):
        merged_webhooks = []
        for wbh in webhooks:
            wbh["type"] = wbh["name"].split("-")[-1]
            sns = getattr(self, f"sns_client_{wbh.get('type')}")
            subs = self.get_subscriptions(sns, wbh.get("sns_arn"))
            for sub in subs:
                wbh_copy = wbh.copy()
                wbh_copy["url"] = sub.get("Endpoint")
                wbh_copy["sub_id"] = sub.get("SubscriptionArn")
                merged_webhooks.append(wbh_copy)
        return merged_webhooks

    def get_subscriptions(self, sns, topic_arn: str):
        paginator = sns.get_paginator("list_subscriptions_by_topic")
        for page in paginator.paginate(TopicArn=topic_arn):
            for sub in page.get("Subscriptions", []):
                if sub.get("Protocol").startswith("http") and sub.get("Endpoint"):
                    yield sub
        return None

    def get_subscription(self, sns, topic_arn: str, webhook_url: str):
        """Get a subscription."""
        subs = self.get_subscriptions(sns, topic_arn)
        return next((sub for sub in subs if sub.get("Endpoint") == webhook_url), None)

    def delete_subscription(self, sns, webhook, webhook_url: str):
        """Delete a subscription."""
        topic_arn = webhook.get("sns_arn")
        subscription = self.get_subscription(sns, topic_arn, webhook_url)
        if subscription:
            if subscription.get("SubscriptionArn") == 'pending subscription':
                raise ValueError("Pending subscription")
            return sns.unsubscribe(SubscriptionArn=subscription.get("SubscriptionArn"))
        return None
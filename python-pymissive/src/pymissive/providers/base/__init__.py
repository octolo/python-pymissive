from providerkit import ProviderBase
import base64
import mimetypes
from typing import Any
from .acknowledgement import AcknowledgementMixin
from .attachments import AttachmentsMixin
from .branded import BrandedMixin
from .email import EmailMixin
from .notification import NotificationMixin
from .postal import PostalMixin
from .sms import SMSMixin
from .voice_call import VoiceCallMixin
import re
import unicodedata
from pymissive import config

defaults_services = {
    "retrieve_webhooks": {
        "fields": config.WEBHOOK_FIELDS,
    },
}


for category, service_cfg in config.MISSIVE_SERVICES.items():
    for service in service_cfg["services"].items():
        for missive_type in config.MISSIVE_TYPES.keys():
            defaults_services[f"{service[0]}_{missive_type}"] = {
                "description": service[1],
                "fields": service_cfg["config"]
            }


class MissiveProviderBase(
    ProviderBase,
    AcknowledgementMixin,
    AttachmentsMixin,
    BrandedMixin,
    EmailMixin,
    NotificationMixin,
    PostalMixin,
    SMSMixin,
    VoiceCallMixin,
):
    """Base class for Missive providers."""
    _default_services_cfg = defaults_services
    provider_key = "key"
    events_association = None

    def _to_base64(self, content):
        if isinstance(content, bytes):
            return base64.b64encode(content).decode("ascii")
        return content

    def _guess_content_type(self, name: str) -> str:
        """Guess MIME type from filename. Scaleway requires a type from its allowed list."""
        guessed, _ = mimetypes.guess_type(name)
        return guessed or "application/octet-stream"

    def get_events_association(self) -> dict[str, str]:
        """Return mapping of provider events to missive event."""
        return self.events_association or {}

    def get_normalize_event(self, data: dict[str, Any]) -> str:
        """Return the normalized event of webhook/email/SMS."""
        return self.events_association.get(data.get("event"), "unknown")

    def get_normalize_webhook_id(self, data: dict) -> str:
        cfg = config.WEBHOOK_FIELDS.get("webhook_id")
        source = cfg.get("source", self.fields_associations.get("webhook_id", "webhook_id"))
        webhook_id = self._normalize_recursive(data, "webhook_id", source)
        if webhook_id:
            return f"{self.name}-{webhook_id}"
        return None

    def normalize_filename(self, name):
        name = unicodedata.normalize("NFKD", name)
        name = re.sub(r"\s+", "_", name)      # spaces -> _
        name = re.sub(r"[^\w\.-]", "", name)  # strip special characters
        return name
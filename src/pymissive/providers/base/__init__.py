from providerkit import ProviderBase
import base64
import mimetypes
from .acknowledgement import AcknowledgementMixin
from .attachments import AttachmentsMixin
from .branded import BrandedMixin
from .email import EmailMixin
from .notification import NotificationMixin
from .postal import PostalMixin
from .sms import SMSMixin
from .voice_call import VoiceCallMixin

from pymissive import config

defaults_services = {
    "get_webhooks": {
        "fields": config.MISSIVE_WEBHOOK_FIELDS,
    },
}

if config is not None:
    
    for missive_type, type_desc in config.MISSIVE_TYPES.items():
        fields_name = config.type_to_fields_mapping.get(missive_type, "MISSIVE_FIELDS_BASE")
        fields = getattr(config, fields_name, config.MISSIVE_FIELDS_BASE)
        
        for service, service_desc in config.MISSIVE_SERVICES.items():
            defaults_services[f"{service}_{missive_type}"] = {
                "fields": fields,
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

    def get_normalize_webhook_id(self, data: dict) -> str:
        return f"{self.name}-{data['id']}"
from providerkit import ProviderBase
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

    # Override to map provider events -> status description
    status_events_association = None

    def get_status_events_association(self) -> dict[str, str]:
        """Return mapping of provider events to status description."""
        from pymissive.config import MISSIVE_STATUS

        association = getattr(self.__class__, "status_events_association", None)
        if association is not None:
            return association

        result = dict(MISSIVE_STATUS)
        events = getattr(self.__class__, "events", None)
        if events:
            for provider_event in events:
                if provider_event not in result:
                    normalized = provider_event.lower().replace("-", "_")
                    result[provider_event] = result.get(normalized, "Pending")
        return result

    def get_normalize_webhook_id(self, data: dict) -> str:
        return f"{self.name}-{data['id']}"
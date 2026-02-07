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

defaults_services = {}

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

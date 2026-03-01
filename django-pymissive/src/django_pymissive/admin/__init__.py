"""Admin configuration for django_pymissive."""

from .document import MissiveDocumentAdmin
from .campaign import MissiveCampaignAdmin
from .event import MissiveEventAdmin
from .recipient import (
    MissiveRecipientAdmin,
    MissiveRecipientEmailInline,
    MissiveRecipientPhoneInline,
    MissiveRecipientAddressInline,
    MissiveRecipientNotificationInline
)
from .missive import MissiveAdmin
from .provider import ProviderAdmin
from .related_object import MissiveRelatedObjectAdmin
from .webhook import MissiveWebhookAdmin
from .service import MissiveServiceAdmin

__all__ = [
    "ProviderAdmin",
    "MissiveCampaignAdmin",
    "MissiveAdmin",
    "MissiveDocumentAdmin",
    "MissiveEventAdmin",
    "MissiveRelatedObjectAdmin",
    "MissiveRecipientAdmin",
    "MissiveRecipientEmailInline",
    "MissiveRecipientPhoneInline",
    "MissiveRecipientAddressInline",
    "MissiveRecipientNotificationInline",
    "MissiveWebhookAdmin",
    "MissiveServiceAdmin",
]

"""Admin configuration for django_pymissive."""

from .config import MissiveConfigAdmin
from .billing import MissiveBillingAdmin, MissiveBillingInline
from .attachment import (
    MissiveAttachmentBaseInline,
    MissiveAttachmentAdmin,
    MissiveAttachmentInline,
    MissiveVirtualAttachmentInline,
    CampaignAttachmentBaseInline,
    CampaignAttachmentInline,
    CampaignVirtualAttachmentInline,
)
from .campaign import MissiveCampaignAdmin
from .event import MissiveEventAdmin
from .recipient import (
    MissiveRecipientAdmin,
    MissiveRecipientEmailInline,
    MissiveRecipientPhoneInline,
    MissiveRecipientAddressInline,
    MissiveRecipientApplicationInline
)
from .missive import MissiveAdmin
from .provider import ProviderAdmin
from .related_object import MissiveRelatedObjectAdmin
from .webhook import MissiveWebhookAdmin
from .service import MissiveServiceAdmin

__all__ = [
    "MissiveBillingAdmin",
    "MissiveBillingInline",
    "MissiveConfigAdmin",
    "ProviderAdmin",
    "MissiveCampaignAdmin",
    "MissiveAdmin",
    "MissiveAttachmentAdmin",
    "MissiveAttachmentBaseInline",
    "MissiveAttachmentInline",
    "MissiveVirtualAttachmentInline",
    "CampaignAttachmentBaseInline",
    "CampaignAttachmentInline",
    "CampaignVirtualAttachmentInline",
    "MissiveEventAdmin",
    "MissiveRelatedObjectAdmin",
    "MissiveRecipientAdmin",
    "MissiveRecipientEmailInline",
    "MissiveRecipientPhoneInline",
    "MissiveRecipientAddressInline",
    "MissiveRecipientApplicationInline",
    "MissiveWebhookAdmin",
    "MissiveServiceAdmin",
]

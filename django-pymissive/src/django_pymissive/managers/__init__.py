"""Managers for django_pymissive."""

from .provider import ProviderManager
from .missive import MissiveManager
from .campaign import MissiveCampaignManager
from .event import MissiveEventManager
from .document import (
    MissiveDocumentManager,
    MissiveAttachmentManager,
    MissiveVirtualAttachmentManager,
    CampaignDocumentManager,
    CampaignAttachmentManager,
    CampaignVirtualAttachmentManager,
)
from .related_object import (
    MissiveRelatedObjectManager,
    CampaignRelatedObjectManager,
)
from .recipient import (
    MissiveRecipientManager,
    MissiveRecipientEmailManager,
    MissiveRecipientPhoneManager,
    MissiveRecipientAddressManager,
    MissiveRecipientNotificationManager,
)

__all__ = [
    "ProviderManager",
    "MissiveManager",
    "MissiveCampaignManager",
    "MissiveEventManager",
    "MissiveDocumentManager",
    "MissiveAttachmentManager",
    "MissiveVirtualAttachmentManager",
    "MissiveRelatedObjectManager",
    "CampaignRelatedObjectManager",
    "MissiveRecipientManager",
    "MissiveRecipientEmailManager",
    "MissiveRecipientPhoneManager",
    "MissiveRecipientAddressManager",
    "MissiveRecipientNotificationManager",
    "CampaignDocumentManager",
    "CampaignAttachmentManager",
    "CampaignVirtualAttachmentManager",
]

"""Managers for django_pymissive."""

from .provider import ProviderManager
from .missive import (
    MissiveManager,
    MissiveMessageManager,
    MissiveHistoryManager,
)
from .campaign import MissiveCampaignManager
from .scheduler import MissiveScheduledCampaignManager
from .event import MissiveEventManager
from .attachment import (
    MissiveBaseAttachmentManager,
    MissiveAttachmentManager,
    MissiveVirtualAttachmentManager,
    CampaignAttachmentManager,
    CampaignVirtualAttachmentManager,
    MissiveProofManager,
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
    MissiveRecipientApplicationManager,
)

__all__ = [
    "ProviderManager",
    "MissiveManager",
    "MissiveMessageManager",
    "MissiveHistoryManager",
    "MissiveCampaignManager",
    "MissiveScheduledCampaignManager",
    "MissiveEventManager",
    "MissiveBaseAttachmentManager",
    "MissiveAttachmentManager",
    "MissiveVirtualAttachmentManager",
    "CampaignAttachmentManager",
    "CampaignVirtualAttachmentManager",
    "MissiveRelatedObjectManager",
    "CampaignRelatedObjectManager",
    "MissiveRecipientManager",
    "MissiveRecipientEmailManager",
    "MissiveRecipientPhoneManager",
    "MissiveRecipientAddressManager",
    "MissiveRecipientApplicationManager",

]

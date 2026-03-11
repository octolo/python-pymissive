from django.db import models

from ..models.choices import MissiveAttachmentType


class MissiveBaseAttachmentManager(models.Manager):
    """Manager for the MissiveAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive", "campaign")
        return qs


class MissiveAttachmentManager(MissiveBaseAttachmentManager):
    """Manager for the MissiveAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            campaign__isnull=True,
            missive__isnull=False,
        )
        return qs


class MissiveVirtualAttachmentManager(MissiveBaseAttachmentManager):
    """Manager for the MissiveVirtualAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(
            attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
            campaign__isnull=True,
            missive__isnull=False,
        )
        return qs


class CampaignAttachmentManager(MissiveBaseAttachmentManager):
    """Manager for the CampaignAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            campaign__isnull=False,
            missive__isnull=True,
        )
        return qs


class CampaignVirtualAttachmentManager(MissiveBaseAttachmentManager):
    """Manager for the CampaignVirtualAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(
            attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT,
            campaign__isnull=False,
            missive__isnull=True,
        )
        return qs
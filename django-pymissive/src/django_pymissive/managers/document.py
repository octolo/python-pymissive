from django.db import models

from ..models.choices import MissiveDocumentType


class MissiveDocumentManager(models.Manager):
    """Manager for the MissiveAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive")
        return qs


class MissiveAttachmentManager(MissiveDocumentManager):
    """Manager for the MissiveAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(document_type=MissiveDocumentType.ATTACHMENT)
        return qs


class MissiveVirtualAttachmentManager(MissiveDocumentManager):
    """Manager for the MissiveVirtualAttachment model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(document_type=MissiveDocumentType.VIRTUAL_ATTACHMENT)
        return qs

"""MissiveAttachment model."""

import os
import uuid
from datetime import date

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .choices import MissiveDocumentType
from ..managers.document import (
    MissiveDocumentManager,
    MissiveAttachmentManager,
    MissiveVirtualAttachmentManager,
    CampaignDocumentManager,
    CampaignAttachmentManager,
    CampaignVirtualAttachmentManager,
)


def _document_upload_to(instance, filename):
    """Return upload path based on document class: missivedocument/ or campaigndocument/."""
    today = date.today()
    prefix = (
        "campaigndocument"
        if "Campaign" in instance.__class__.__name__
        else "missivedocument"
    )
    return f"missive/{prefix}/{today:%Y/%m/%d}/{filename}"


class BaseDocument(models.Model):
    """File attachment for missives or any other model."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )

    document_type = models.CharField(
        max_length=50,
        choices=MissiveDocumentType.choices,
        default=MissiveDocumentType.ATTACHMENT,
        verbose_name=_("Document Type"),
        help_text=_("Type of document (attachment, signature, receipt, proof, other)"),
    )

    document_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Object Type"),
        help_text=_("Type of model to which this file is attached"),
    )

    document_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Object ID"),
        help_text=_("ID of the object to which this file is attached"),
    )

    document_object_arguments = models.JSONField(
        default=dict({"method": "get_document", "args": [], "kwargs": {}}),
        blank=True,
        verbose_name=_("Document Object Arguments"),
        help_text=_("Arguments to pass to the file method (as dict for **kwargs)"),
    )

    document = models.FileField(
        upload_to=_document_upload_to,
        blank=True,
        null=True,
        verbose_name=_("Local File"),
        help_text=_("Leave blank if the document is hosted externally"),
    )

    document_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Document Metadata"),
        help_text=_("Metadata of the document"),
    )

    linked = models.BooleanField(
        default=True,
        verbose_name=_("Linked"),
        help_text=_("Indicates if the document is linked to a related object"),
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Order"),
        help_text=_("Display order"),
    )

    document_object = GenericForeignKey("document_content_type", "document_object_id")

    class Meta:
        abstract = True
        verbose_name = _("Document")
        verbose_name_plural = _("Documents")
        ordering = ["order",]

    @property
    def can_be_modified(self):
        if hasattr(self, "missive"):
            return self.missive.can_be_modified
        if hasattr(self, "campaign"):
            return self.campaign.can_be_modified
        return False

    def can_access_document(self):
        """Checks if the document can be accessed."""
        return all(
            [
                self.document_content_type,
                self.document_object_id,
                self.document_object_arguments,
            ]
        )

    def get_virtual_attachment(self):
        """Gets the virtual attachment."""
        get_method = self.document_object_arguments["method"]
        args = self.document_object_arguments["args"]
        kwargs = self.document_object_arguments["kwargs"]
        return getattr(self.document_object, get_method)(*args, **kwargs)

    def get_document(self):
        """Gets the document."""
        if self.document_type == MissiveDocumentType.VIRTUAL_ATTACHMENT:
            return self.get_virtual_attachment()
        return self.document

    @property
    def attachment_url(self):
        return self.get_serialized_document(linked=True, ignore_content=True)

    @property
    def attachment(self):
        return self.get_serialized_document(linked=True, ignore_content=False)

    def get_serialized_document(self, linked=False, ignore_content=False):
        """Gets the serialized document."""
        document = self.get_document()
        name = getattr(document, "name") or "unnamed_document"
        url_name = (
            "django_pymissive:missive_document_download"
            if isinstance(self, MissiveDocument)
            else "django_pymissive:campaign_document_download"
        )
        url = reverse(url_name, args=[self.id])
        data = {
            "name": os.path.basename(name),
            "url": url,
        }
        if linked or ignore_content:
            return data
        if hasattr(document, "seek"):
            document.seek(0)
        data["content"] = document.read()
        return data

    def clean(self):
        """Validates document."""
        if not self.document and not self.can_access_document():
            raise ValidationError(
                _(
                    "You must provide either a local document or a method to access the document."
                )
            )


class MissiveDocument(BaseDocument):
    """Document for missives."""
    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missivedocument",
        verbose_name=_("Missive"),
        null=True,
        blank=True,
        help_text=_("Missive to which this file is attached"),
    )

    class Meta:
        verbose_name = _("Missive Document")
        verbose_name_plural = _("Missive Documents")
        ordering = ["order",]


class MissiveAttachment(MissiveDocument):
    """Attachment for missives."""

    objects = MissiveAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")


class MissiveVirtualAttachment(MissiveDocument):
    """Virtual attachment for missives."""

    objects = MissiveVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Virtual Attachment")
        verbose_name_plural = _("Virtual Attachments")


class CampaignDocument(BaseDocument):
    """Document for campaigns."""
    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaigndocument",
        verbose_name=_("Campaign"),
        null=True,
        blank=True,
        help_text=_("Campaign to which this file is attached"),
    )

    class Meta:
        verbose_name = _("Campaign Document")
        verbose_name_plural = _("Campaign Documents")
        ordering = ["order",]


class CampaignAttachment(CampaignDocument):
    """Attachment for campaigns."""

    objects = CampaignAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Attachment")
        verbose_name_plural = _("Campaign Attachments")


class CampaignVirtualAttachment(CampaignDocument):
    """Virtual attachment for campaigns."""

    objects = CampaignVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Virtual Attachment")
        verbose_name_plural = _("Campaign Virtual Attachments")

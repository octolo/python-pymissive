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

from .base import CommentTimestampedModel
from .choices import MissiveAttachmentType
from ..managers.attachment import (
    MissiveBaseAttachmentManager,
    MissiveAttachmentManager,
    MissiveVirtualAttachmentManager,
    CampaignAttachmentManager,
    CampaignVirtualAttachmentManager,
)
from ..fields import JSONField

def _attachment_upload_to(instance, filename):
    """Return upload path based on attachment class."""
    today = date.today()
    prefix = "campaignattachment" if instance.campaign else "missiveattachment"
    return f"missive/{prefix}/{today:%Y/%m/%d}/{filename}"


class MissiveBaseAttachment(CommentTimestampedModel):
    """File attachment for missives or any other model."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )

    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaigndocument",
        verbose_name=_("Campaign"),
        null=True,
        blank=True,
        help_text=_("Campaign to which this file is attached"),
    )
    
    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missivedocument",
        verbose_name=_("Missive"),
        null=True,
        blank=True,
        help_text=_("Missive to which this file is attached"),
    )

    attachment_type = models.CharField(
        max_length=50,
        choices=MissiveAttachmentType.choices,
        default=MissiveAttachmentType.ATTACHMENT,
        verbose_name=_("Attachment Type"),
        help_text=_("Type of attachment (attachment, signature, receipt, proof, other)"),
    )

    attachment_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Object Type"),
        help_text=_("Type of model to which this file is attached"),
    )

    attachment_object_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Object ID"),
        help_text=_("ID of the object to which this file is attached"),
    )

    attachment_object_arguments = JSONField(
        default=dict({"method": "get_attachment", "args": [], "kwargs": {}}),
        blank=True,
        verbose_name=_("Attachment Object Arguments"),
        help_text=_("Arguments to pass to the file method (as dict for **kwargs)"),
    )

    attachment_file = models.FileField(
        upload_to=_attachment_upload_to,
        blank=True,
        null=True,
        verbose_name=_("Attachment File"),
        help_text=_("Leave blank if the attachment is hosted externally"),
    )

    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )

    linked = models.BooleanField(
        default=True,
        verbose_name=_("Linked"),
        help_text=_("Indicates if the attachment is linked to a related object"),
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Order"),
        help_text=_("Display order"),
    )

    attachment_object = GenericForeignKey("attachment_content_type", "attachment_object_id")
    objects = MissiveBaseAttachmentManager()

    class Meta:
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")
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
                self.attachment_content_type,
                self.attachment_object_id,
                self.attachment_object_arguments,
            ]
        )

    def get_virtual_attachment(self):
        """Gets the virtual attachment by calling the configured method on the related object."""
        get_method = self.attachment_object_arguments["method"]
        args = self.attachment_object_arguments.get("args", [])
        kwargs = self.attachment_object_arguments.get("kwargs", {})
        return getattr(self.attachment_object, get_method)(*args, **kwargs)

    def get_attachment(self):
        """Returns the raw file or virtual attachment object."""
        if self.attachment_type == MissiveAttachmentType.VIRTUAL_ATTACHMENT:
            return self.get_virtual_attachment()
        return self.attachment_file

    @property
    def attachment_url(self):
        return self.get_serialized_attachment(linked=True, ignore_content=True)

    def get_serialized_attachment(self, linked=False, ignore_content=False):
        """Returns a serialized dict for this attachment."""
        attachment = self.get_attachment()
        name = getattr(attachment, "name", None) or "unnamed_attachment"
        scope = "campaign" if self.campaign_id else "missive"
        url = reverse("django_pymissive:missive_attachment_download", args=[scope, self.id])
        data = {
            "name": os.path.basename(name),
            "url": url,
        }
        if linked or ignore_content:
            return data
        if hasattr(attachment, "seek"):
            attachment.seek(0)
        data["content"] = attachment.read()
        return data

    def clean(self):
        """Validates attachment."""
        if not self.attachment_file and not self.can_access_attachment():
            raise ValidationError(
                _(
                    "You must provide either a local attachment or a method to access the attachment."
                )
            )

class MissiveAttachment(MissiveBaseAttachment):
    """Attachment for missives."""

    objects = MissiveAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")


class MissiveVirtualAttachment(MissiveBaseAttachment):
    """Virtual attachment for missives."""

    objects = MissiveVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Virtual Attachment")
        verbose_name_plural = _("Virtual Attachments")


class CampaignAttachment(MissiveBaseAttachment):
    """Attachment for campaigns."""

    objects = CampaignAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Attachment")
        verbose_name_plural = _("Campaign Attachments")


class CampaignVirtualAttachment(MissiveBaseAttachment):
    """Virtual attachment for campaigns."""

    objects = CampaignVirtualAttachmentManager()

    class Meta:
        proxy = True
        verbose_name = _("Campaign Virtual Attachment")
        verbose_name_plural = _("Campaign Virtual Attachments")

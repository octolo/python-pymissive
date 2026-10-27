"""MissiveRelatedObject model for linking missives to other models."""

import logging
from typing import ClassVar

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from .mixins import CommentTimestampedModel
from ..managers.related_object import (
    CampaignRelatedObjectManager,
    MissiveRelatedObjectManager,
    object_id_value,
)

logger = logging.getLogger(__name__)


class BaseRelatedObject(CommentTimestampedModel):
    """Model to link a missive or campaign to any other Django model."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
        help_text=_("Type of the related object"),
    )
    object_id = models.CharField(
        max_length=255,
        verbose_name=_("Object ID"),
        help_text=_("ID of the related object (integer pk as well as UUID)"),
    )
    content_object = GenericForeignKey("content_type", "object_id")
    object_str = models.CharField(
        editable=False,
        max_length=500,
        verbose_name=_("Object String Representation"),
        help_text=_("String representation of the related object (saved for reference if object is deleted)"),
    )
    objects: ClassVar[models.Manager] = MissiveRelatedObjectManager()

    class Meta:
        abstract = True
        verbose_name = _("Related Object")
        verbose_name_plural = _("Related Objects")
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """Normalize the object id and save the string representation."""
        if self.object_id is not None:
            model = self.content_type.model_class()
            self.object_id = object_id_value(
                self.object_id,
                pk_field=model._meta.pk if model is not None else None,
            )
        if self.content_object:
            try:
                self.object_str = str(self.content_object)
            except Exception:
                logger.warning(
                    "Unable to render related object %s:%s",
                    self.content_type_id,
                    self.object_id,
                    exc_info=True,
                )
        super().save(*args, **kwargs)


class MissiveRelatedObject(BaseRelatedObject):
    """Model to link a missive to any other Django model."""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiverelatedobject",
        verbose_name=_("Missive"),
        help_text=_("Missive to which this object is related"),
    )

    objects: ClassVar[models.Manager] = MissiveRelatedObjectManager()

    class Meta:
        verbose_name = _("Missive Related Object")
        verbose_name_plural = _("Missive Related Objects")
        ordering = ["-created_at"]
        # The generic FK is only ever queried the other way round: "which
        # missives point at this object?".
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        if self.content_object:
            return f"{self.missive} -> {self.content_object}"
        elif self.object_str:
            return f"{self.missive} -> {self.object_str} (deleted)"
        return f"{self.missive} -> {self.content_type} #{self.object_id}"


class CampaignRelatedObject(BaseRelatedObject):
    """Model to link a campaign to any other Django model."""

    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.CASCADE,
        related_name="to_campaignrelatedobject",
        verbose_name=_("Campaign"),
        help_text=_("Campaign to which this object is related"),
    )

    objects: ClassVar[models.Manager] = CampaignRelatedObjectManager()

    class Meta:
        verbose_name = _("Campaign Related Object")
        verbose_name_plural = _("Campaign Related Objects")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        if self.content_object:
            return f"{self.campaign} -> {self.content_object}"
        elif self.object_str:
            return f"{self.campaign} -> {self.object_str} (deleted)"
        return f"{self.campaign} -> {self.content_type} #{self.object_id}"

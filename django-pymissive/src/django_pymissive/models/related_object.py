"""MissiveRelatedObject model for linking missives to other models."""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from ..managers.related_object import MissiveRelatedObjectManager


class MissiveRelatedObject(models.Model):
    """Model to link a missive to any other Django model."""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiverelatedobject",
        verbose_name=_("Missive"),
        help_text=_("Missive to which this object is related"),
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
        help_text=_("Type of the related object"),
    )
    object_id = models.PositiveIntegerField(
        verbose_name=_("Object ID"),
        help_text=_("ID of the related object"),
    )
    content_object = GenericForeignKey("content_type", "object_id")
    object_str = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Object String Representation"),
        help_text=_(
            "String representation of the related object (saved for reference if object is deleted)"
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At"),
    )

    objects = MissiveRelatedObjectManager()

    class Meta:
        verbose_name = _("Related Object")
        verbose_name_plural = _("Related Objects")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["missive", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def save(self, *args, **kwargs):
        """Save the object string representation before saving."""
        if self.content_object:
            try:
                self.object_str = str(self.content_object)
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        if self.content_object:
            return f"{self.missive} -> {self.content_object}"
        elif self.object_str:
            return f"{self.missive} -> {self.object_str} (deleted)"
        return f"{self.missive} -> {self.content_type} #{self.object_id}"

"""Abstract base models for django_pymissive."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CommentTimestampedModel(models.Model):
    """Abstract model providing comment, created_at and updated_at fields."""

    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Comment"),
        help_text=_("Internal comment or note"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        editable=False,
        verbose_name=_("Created At"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        editable=False,
        verbose_name=_("Updated At"),
    )

    class Meta:
        abstract = True

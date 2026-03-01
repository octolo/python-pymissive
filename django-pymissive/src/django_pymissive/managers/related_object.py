from django.db import models


class MissiveRelatedObjectManager(models.Manager):
    """Manager for the MissiveRelatedObject model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive")
        return qs

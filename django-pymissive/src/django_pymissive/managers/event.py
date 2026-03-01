from django.db import models


class MissiveEventManager(models.Manager):
    """Manager for the MissiveEvent model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive", "recipient")
        return qs

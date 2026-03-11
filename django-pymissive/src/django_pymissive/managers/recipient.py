from django.db import models
from django.db.models.expressions import Subquery, OuterRef
from django.db.models import F, Max
from django.db.models.functions import Coalesce

from ..models.choices import MissiveSupport 

class MissiveRecipientManager(models.Manager):
    """Manager for the MissiveRecipient model."""

    def last_event_subquery(self, field: str = "event"):
        from ..models.event import MissiveEvent

        return Subquery(
            MissiveEvent.objects.filter(
                missive_id=OuterRef("missive_id"),
                recipient_id=OuterRef("id"),
            )
            .order_by("-occurred_at", "-id")
            .values("event")[:1],
            output_field=models.CharField(),
        )

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("missive")
        qs = qs.prefetch_related("to_recipientevent")
        qs = qs.annotate(
            count_event=models.Count(
                "to_recipientevent",
            ),
            last_event=self.last_event_subquery(field="event"),
            last_event_description=self.last_event_subquery(field="description"),
            last_event_date=Coalesce(
                Max("to_recipientevent__occurred_at"), F("created_at")
            ),
        )
        return qs


class MissiveRecipientEmailManager(models.Manager):
    """Manager for the MissiveRecipientEmail model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.EMAIL)
        return qs

class MissiveRecipientPhoneManager(models.Manager):
    """Manager for the MissiveRecipientPhone model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.PHONE)
        return qs

class MissiveRecipientAddressManager(models.Manager):
    """Manager for the MissiveRecipientAddress model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.ADDRESS)
        return qs

class MissiveRecipientNotificationManager(models.Manager):
    """Manager for the MissiveRecipientNotification model."""

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(recipient_support=MissiveSupport.NOTIFICATION)
        return qs

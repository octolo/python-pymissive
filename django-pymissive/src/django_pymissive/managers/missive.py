from django.db import models
from django.db.models.expressions import Subquery, OuterRef
from django.db.models import F, Max, Q
from django.db.models.functions import Coalesce

from ..models.choices import MissiveRecipientType, MissiveDocumentType


class MissiveManager(models.Manager):
    """Manager for the Missive model."""

    def last_event_subquery(self, field: str = "event"):
        from ..models.event import MissiveEvent

        return Subquery(
            MissiveEvent.objects.filter(
                missive=OuterRef("pk"),
            )
            .order_by("-occurred_at", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def last_scheduled_subquery(self, field: str = "event"):
        from ..models.campaign import MissiveScheduledCampaign

        return Subquery(
            MissiveScheduledCampaign.objects.filter(
                campaign=OuterRef("campaign_id"),
                send_date__isnull=False,
            )
            .order_by(f"-{field}", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.select_related("campaign")
        qs = qs.prefetch_related(
            "to_missiverecipient",
            "to_missivedocument",
            "to_missiveevent",
            "to_missiverelatedobject",
        )
        qs = qs.annotate(
            count_event=models.Count("to_missiveevent", distinct=True),
            count_related_object=models.Count("to_missiverelatedobject", distinct=True),
            count_recipient=models.Count("to_missiverecipient", distinct=True),
            count_attachment=models.Count("to_missivedocument", distinct=True),
            count_target=models.Count(
                "to_missiverecipient",
                distinct=True,
                filter=~Q(
                    to_missiverecipient__recipient_type__in=[
                        MissiveRecipientType.SENDER,
                        MissiveRecipientType.REPLY_TO,
                    ],
                ),
            ),
            last_event=self.last_event_subquery(field="event"),
            last_event_description=self.last_event_subquery(field="description"),
            last_event_date=Coalesce(
                Max("to_missiveevent__occurred_at"), F("created_at")
            ),
            last_campaign_send_date=self.last_scheduled_subquery("send_date"),
            last_campaign_ended_at=self.last_scheduled_subquery("ended_at"),
        )
        return qs

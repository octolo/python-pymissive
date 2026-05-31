"""Manager for MissiveCampaign model."""

from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.db.models.expressions import Subquery, OuterRef
from django.db.models.functions import Coalesce
from pymissive.config import MISSIVE_TYPES

from ..models.choices import MissiveStatus


class MissiveCampaignManager(models.Manager):
    """Manager for MissiveCampaign with annotated counts."""

    def last_scheduled_subquery(self, field: str = "event"):
        from ..models.scheduler import MissiveScheduledCampaign

        return Subquery(
            MissiveScheduledCampaign.objects.filter(
                campaign=OuterRef("pk"),
            )
            .order_by(f"-{field}", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def pct_expr(self, cnt):
        return Coalesce(
            Case(
                When(count_recipient=0, then=Value(0.0)),
                default=cnt * 100.0 / F("count_recipient"),
                output_field=models.FloatField(),
            ),
            Value(0.0),
        )

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.annotate(
            last_send_date=self.last_scheduled_subquery("send_date"),
            last_ended_at=self.last_scheduled_subquery("ended_at"),
            count_missive=models.Count("to_missive", distinct=True),
            count_recipient=models.Count("to_missive__to_missiverecipient", distinct=True),
            count_event=models.Count("to_missive__to_missiveevent", distinct=True),
            count_related_object=models.Count("to_campaignrelatedobject", distinct=True),
            count_attachment=models.Count("to_campaigndocument", distinct=True),
            **{
                f"count_missive_{status.value.lower()}": models.Count(
                    "to_missive",
                    filter=Q(to_missive__status=status),
                    distinct=True,
                )
                for status in MissiveStatus
            },
            **{
                f"count_type_{type_key}": models.Count(
                    "to_missive",
                    filter=Q(to_missive__missive_type=type_key),
                    distinct=True,
                )
                for type_key in MISSIVE_TYPES
            },
            **{
                f"count_recipient_{status.value.lower()}": models.Count(
                    "to_missive__to_missiverecipient",
                    distinct=True,
                    filter=Q(to_missive__to_missiverecipient__status=status),
                )
                for status in MissiveStatus
            },
        )
        qs = qs.annotate(
            **{
                f"pct_recipient_{status.value.lower()}": self.pct_expr(F(f"count_recipient_{status.value.lower()}"))
                for status in MissiveStatus
            },
        )
        return qs

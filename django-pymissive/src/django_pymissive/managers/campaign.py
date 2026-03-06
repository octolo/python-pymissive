"""Manager for MissiveCampaign model."""

from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.db.models.expressions import Subquery, OuterRef
from django.db.models.functions import Coalesce

from ..models.choices import MissiveStatus


class MissiveCampaignManager(models.Manager):
    """Manager for MissiveCampaign with annotated counts."""

    def last_scheduled_subquery(self, field: str = "event"):
        from ..models.campaign import MissiveScheduledCampaign

        return Subquery(
            MissiveScheduledCampaign.objects.filter(
                campaign=OuterRef("pk"),
            )
            .order_by(f"-{field}", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.annotate(
            last_send_date=self.last_scheduled_subquery("send_date"),
            last_ended_at=self.last_scheduled_subquery("ended_at"),
            count_missive=models.Count("to_missive", distinct=True),
            count_missive_draft=models.Count("to_missive", filter=Q(to_missive__status=MissiveStatus.DRAFT), distinct=True),
            count_recipient=models.Count(
                "to_missive__to_missiverecipient", distinct=True
            ),
            count_recipient_failed=models.Count(
                "to_missive__to_missiverecipient",
                distinct=True,
                filter=Q(to_missive__to_missiverecipient__status=MissiveStatus.FAILED),
            ),
            count_recipient_success=models.Count(
                "to_missive__to_missiverecipient",
                distinct=True,
                filter=Q(to_missive__to_missiverecipient__status=MissiveStatus.SUCCESS),
            ),
            count_recipient_processing=models.Count(
                "to_missive__to_missiverecipient",
                distinct=True,
                filter=Q(
                    to_missive__to_missiverecipient__status=MissiveStatus.PROCESSING
                ),
            ),
            count_related_object=models.Count("to_campaignrelatedobject", distinct=True),
            count_attachment=models.Count("to_campaigndocument", distinct=True),
        )

        def pct_expr(cnt):
            return Coalesce(
                Case(
                    When(count_recipient=0, then=Value(0.0)),
                    default=cnt * 100.0 / F("count_recipient"),
                    output_field=models.FloatField(),
                ),
                Value(0.0),
            )

        qs = qs.annotate(
            pct_failed=pct_expr(F("count_recipient_failed")),
            pct_success=pct_expr(F("count_recipient_success")),
            pct_processing=pct_expr(F("count_recipient_processing")),
        )
        return qs

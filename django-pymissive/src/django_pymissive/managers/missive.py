from django.db import models
from django.db.models.expressions import Subquery, OuterRef
from django.db.models import F, Max, Q, Sum
from django.db.models.functions import Coalesce

from ..models.choices import MissiveAttachmentType, MissiveThreadType


class BaseMissiveManager(models.Manager):
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

    def get_queryset_annotated(self):
        qs = super().get_queryset()
        qs = qs.select_related("campaign")
        qs = qs.prefetch_related(
            "to_missiverecipient",
            "to_missiveattachment",
            "to_missiveevent",
            "to_missiverelatedobject",
        )
        qs = qs.annotate(
            count_event=models.Count("to_missiveevent", distinct=True),
            count_related_object=models.Count("to_missiverelatedobject", distinct=True),
            count_recipient=models.Count("to_missiverecipient", distinct=True),
            count_attachment=models.Count("to_missiveattachment", distinct=True),
            last_event=self.last_event_subquery(field="event"),
            last_event_description=self.last_event_subquery(field="description"),
            last_event_date=Coalesce(
                Max("to_missiveevent__occurred_at"), F("created_at")
            ),
            last_campaign_send_date=self.last_scheduled_subquery("send_date"),
            last_campaign_ended_at=self.last_scheduled_subquery("ended_at"),
            total_billing_amount=Sum("to_missiveevent__billing_amount"),
            total_estimate_amount=Sum("to_missiveevent__estimate_amount"),
            total_billed_amount=Sum("to_missiveevent__billing_amount", filter=Q(to_missiveevent__is_billed=True)),
        ).annotate(
            is_billable=models.Case(
                models.When(total_billing_amount__gt=0, then=True),
                default=False,
                output_field=models.BooleanField(),
            ),
            is_billed=models.Case(
                models.When(
                    Q(total_billing_amount__gt=0)
                    & Q(total_billing_amount=F("total_billed_amount")),
                    then=True,
                ),
                default=False,
                output_field=models.BooleanField(),
            ),
        )
        return qs


class MissiveManager(BaseMissiveManager):
    """Manager for the Missive model."""


    def count_history(self):
        # Use _base_manager to avoid recursion (get_queryset annotates with count_history)
        qs = self.model._base_manager.get_queryset().filter(
            thread_type=MissiveThreadType.HISTORY, thread_id=OuterRef("thread_id")
        )
        return Subquery(
            qs.values("thread_id").annotate(count=models.Count("id")).values("count"),
            output_field=models.IntegerField(),
        )

    def count_message(self):
        # Use _base_manager to avoid recursion (get_queryset annotates with count_message)
        qs = self.model._base_manager.get_queryset().filter(
            thread_type=MissiveThreadType.MESSAGE, thread_id=OuterRef("thread_id")
        )
        return Subquery(
            qs.values("thread_id").annotate(count=models.Count("id")).values("count"),
            output_field=models.IntegerField(),
        )

    def get_queryset(self):
        qs = super().get_queryset_annotated()
        qs = qs.annotate(
            count_history=self.count_history(),
            count_message=self.count_message(),
        )
        return qs


class MissiveHistoryManager(BaseMissiveManager):
    """Manager for the MissiveHistory model."""

    def get_queryset(self):
        qs = super().get_queryset_annotated()
        qs = qs.filter(thread_type=MissiveThreadType.HISTORY)
        return qs


class MissiveMessageManager(BaseMissiveManager):
    """Manager for the MissiveMessage model."""

    def get_queryset(self):
        qs = super().get_queryset_annotated()
        qs = qs.select_related("message_by")
        qs = qs.filter(thread_type=MissiveThreadType.MESSAGE)
        return qs
from django.db import models
from django.db.models.expressions import Subquery, OuterRef
from django.db.models import F, Max, Min, Q, Sum, Prefetch
from django.db.models.functions import Coalesce
from pymissive.config import SENT_EVENTS

from ..models.choices import (
    MissiveThreadType,
    MissiveStatus,
    MissiveRecipientType,
)


# Attribute name used by Missive.first_recipient to read prefetched data.
FIRST_RECIPIENTS_CACHE_ATTR = "_first_recipients_cache"


def count_annotation_names() -> frozenset:
    """Every name :meth:`MissiveQuerySet.with_counts` annotates.

    Derived rather than listed again: a counter added to
    :meth:`MissiveQuerySet.with_counts` is readable on a non-annotated missive
    at the same time (see :meth:`~django_pymissive.models.missive.Missive._annotation`).
    """
    names = {
        "last_campaign_send_date",
        "last_campaign_ended_at",
        "count_recipient",
        "count_event",
        "last_event",
        "last_event_reason",
        "last_event_date",
        "sent_at",
        "count_related_object",
        "count_attachment",
        "total_billing_amount",
        "total_estimate_amount",
        "total_billed_amount",
        "is_billable",
        "is_billed",
        "count_history",
        "count_message",
    }
    names.update(
        f"count_recipient_{status.value.lower()}" for status in MissiveStatus
    )
    return frozenset(names)


class MissiveQuerySet(models.QuerySet):
    """QuerySet exposing the missive counters as opt-in annotations."""

    def with_counts(self):
        """Annotate the counters :func:`count_annotation_names` enumerates.

        Opt-in, and deliberately not applied in ``get_queryset()``: the join
        aggregates force a ``GROUP BY`` on the missive's columns (including
        ``body_rich`` / ``body_text``), which a plain lookup — a ``.get(pk=…)``,
        a webhook ``get_by_external_id``, ``campaign.to_missive`` — would pay
        for nothing. Reading a counter without this call still works (see
        :meth:`~django_pymissive.models.missive.Missive._annotation`), at one
        query per instance; annotate here as soon as a list displays them.
        """
        manager = self.model._default_manager
        qs = self.annotate(**manager._count_annotations())
        # Second annotate: is_billable / is_billed read totals declared above.
        qs = qs.annotate(**manager._derived_count_annotations())
        qs = qs.annotate(**manager._thread_count_annotations())
        return qs

    def with_related(self):
        """Prefetch all reverse FKs (recipients, attachments, events, billings, related).

        Opt-in for code paths that iterate missives and access their full
        related sets (e.g. ``sync_events`` / ``sync_billings`` management
        commands, batch sending).

        Note: :pyattr:`Missive.recipients` / ``cc`` / ``bcc`` properties call
        ``.filter(...)`` and therefore re-query even when prefetched; iterate
        ``self.to_missiverecipient.all()`` and filter in Python to benefit
        from this cache.
        """
        return self.prefetch_related(
            "to_missiverecipient",
            "to_missiveattachment",
            "to_missiveevent",
            "to_missivebilling",
            "to_missiverelatedobject",
        )


class BaseMissiveManager(models.Manager.from_queryset(MissiveQuerySet)):
    """Manager for the Missive model.

    ``get_queryset()`` stays a plain lookup. The counters live in
    :meth:`MissiveQuerySet.with_counts`. They remain readable on a missive
    nobody annotated, through :meth:`Missive._annotation`.
    """

    def first_recipients_prefetch(self) -> Prefetch:
        """Prefetch main recipients (RECIPIENT type only) into ``_first_recipients_cache``.

        Used by :pyattr:`Missive.first_recipient` to avoid N+1 in admin
        changelists or anywhere a queryset of missives is iterated.
        """
        from ..models.recipient import MissiveRecipient

        return Prefetch(
            "to_missiverecipient",
            queryset=(
                MissiveRecipient.objects
                .filter(recipient_type=MissiveRecipientType.RECIPIENT)
                .order_by("name", "id")
            ),
            to_attr=FIRST_RECIPIENTS_CACHE_ATTR,
        )

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
        from ..models.scheduler import MissiveScheduledCampaign

        return Subquery(
            MissiveScheduledCampaign.objects.filter(
                campaign=OuterRef("campaign_id"),
                send_date__isnull=False,
            )
            .order_by(f"-{field}", "-id")
            .values(field)[:1],
            output_field=models.CharField(),
        )

    def sent_at_expr(self):
        """When the missive actually left, from its events.

        ``Missive`` has no ``sent_at`` column, and ``updated_at`` is bumped by
        any later save, so neither can date a send. The oldest event proving the
        missive left the system (:data:`pymissive.config.SENT_EVENTS`) does.
        ``NULL`` while nothing has been sent.
        """
        return Min(
            "to_missiveevent__occurred_at",
            filter=Q(to_missiveevent__event__in=SENT_EVENTS),
        )

    def is_billable_expr(self):
        return models.Case(
            models.When(total_billing_amount__gt=0, then=True),
            default=False,
            output_field=models.BooleanField(),
        )

    def is_billed_expr(self):
        return models.Case(
            models.When(
                Q(total_billing_amount__gt=0)
                & Q(total_billing_amount=F("total_billed_amount")),
                then=True,
            ),
            default=False,
            output_field=models.BooleanField(),
        )

    def total_billing_expr(self, field: str, is_billed: bool = False):
        from ..models.billing import MissiveBilling
        q_billed = Q(is_billed=True, missive_id=OuterRef("id")) if is_billed else Q(missive_id=OuterRef("id"))
        return Subquery(
            MissiveBilling.objects.filter(q_billed)
            .order_by()
            .values("missive_id")
            .annotate(total=Sum(field))
            .values("total")[:1],
            output_field=models.DecimalField(max_digits=10, decimal_places=4),
        )

    def count_missive_thread(self, thread_type: MissiveThreadType):
        qs = self.model._base_manager.get_queryset().filter(
            thread_type=thread_type, thread_id=OuterRef("thread_id")
        )
        return Subquery(
            qs.values("thread_id").annotate(count=models.Count("id")).values("count"),
            output_field=models.IntegerField(),
        )

    def _count_annotations(self) -> dict:
        return {
            "last_campaign_send_date": self.last_scheduled_subquery("send_date"),
            "last_campaign_ended_at": self.last_scheduled_subquery("ended_at"),
            "count_recipient": models.Count(
                "to_missiverecipient",
                distinct=True,
                filter=Q(to_missiverecipient__recipient_type=MissiveRecipientType.RECIPIENT),
            ),
            "count_event": models.Count("to_missiveevent", distinct=True),
            "last_event": self.last_event_subquery(field="event"),
            "last_event_reason": self.last_event_subquery(field="reason"),
            "last_event_date": Coalesce(Max("to_missiveevent__occurred_at"), F("created_at")),
            "sent_at": self.sent_at_expr(),
            "count_related_object": models.Count("to_missiverelatedobject", distinct=True),
            "count_attachment": models.Count("to_missiveattachment", distinct=True),
            "total_billing_amount": self.total_billing_expr("billing_amount"),
            "total_estimate_amount": self.total_billing_expr("estimate_amount"),
            "total_billed_amount": self.total_billing_expr("billing_amount", is_billed=True),
            **{
                f"count_recipient_{status.value.lower()}": models.Count(
                    "to_missiverecipient",
                    distinct=True,
                    filter=Q(to_missiverecipient__status=status),
                )
                for status in MissiveStatus
            },
        }

    def _derived_count_annotations(self) -> dict:
        return {
            "is_billable": self.is_billable_expr(),
            "is_billed": self.is_billed_expr(),
        }

    def _thread_count_annotations(self) -> dict:
        return {
            "count_history": self.count_missive_thread(thread_type=MissiveThreadType.HISTORY),
            "count_message": self.count_missive_thread(thread_type=MissiveThreadType.MESSAGE),
        }

    def get_queryset_annotated(self):
        """Alias for :meth:`MissiveQuerySet.with_counts`."""
        return self.get_queryset().with_counts()


class MissiveManager(BaseMissiveManager):
    """Manager for the Missive model."""

    def get_by_external_id(self, external_id):
        """Return the missive a provider id refers to, or ``None``.

        A plain ``.get()`` cannot be used: duplicate ``external_id`` values are
        legitimate. ``retrieve_from_provider`` creates a second row on purpose,
        and a dry-run resend reuses ``dry-run:<thread_id>`` because the thread
        id is carried over. Resolve to the live attempt first, then to the most
        recent row, so webhooks and billings stay deterministic instead of
        raising ``MultipleObjectsReturned`` and losing the event.
        """
        if external_id in (None, ""):
            return None
        qs = self.filter(external_id=external_id)
        return (
            qs.filter(thread_type=MissiveThreadType.MISSIVE).order_by("-created_at").first()
            or qs.order_by("-created_at").first()
        )


class MissiveHistoryManager(BaseMissiveManager):
    """Manager for the MissiveHistory model."""

    def get_queryset(self):
        return super().get_queryset().filter(thread_type=MissiveThreadType.HISTORY)


class MissiveMessageManager(BaseMissiveManager):
    """Manager for the MissiveMessage model."""

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related("message_by")
            .filter(thread_type=MissiveThreadType.MESSAGE)
        )

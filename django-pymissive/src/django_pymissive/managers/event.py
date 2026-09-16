from django.db import models
from django.db.models import Count, F, Q, Window
from django.db.models.functions import RowNumber

from pymissive.config import SUCCESSFUL_EVENTS, FAILED_EVENTS, INFO_EVENTS

# Same value as ``choices.CANCELLED_EVENT`` — keep the manager free of model imports.
_CANCELLED_EVENT = "cancelled"


class MissiveEventManager(models.Manager):
    """Manager for the MissiveEvent model."""

    def get_event_counts(self, missive=None, recipient=None):
        """Return (success, processing, failed, cancelled) from last event per recipient.

        Missive-level events (``recipient_id`` is NULL, e.g. a leftover
        recipient-less ``submitted``) are intentionally excluded: the
        status is derived from the latest event of each *recipient*. Without
        this filter a fully-delivered missive ends up as ``PARTIALLY_SUCCESS``
        because the missive-level ``request`` event is counted as a phantom
        "in-progress" recipient.

        Counted in SQL: this runs on every event for both the missive and each
        recipient, and the rows carry JSON ``trace``/``metadata`` that must not
        be loaded just to read ``event``.
        """
        qs = self.filter(event__isnull=False, recipient__isnull=False)
        if missive is not None:
            qs = qs.filter(missive=missive)
        if recipient is not None:
            qs = qs.filter(recipient=recipient)

        # pk breaks ties so that equal ``occurred_at`` values (providers often
        # send whole-second timestamps) resolve to the row inserted last.
        latest_per_recipient = qs.annotate(
            position=Window(
                RowNumber(),
                partition_by=F("recipient_id"),
                order_by=[F("occurred_at").desc(), F("pk").desc()],
            )
        ).filter(position=1)

        failed_events = [event for event in FAILED_EVENTS if event != _CANCELLED_EVENT]
        counts = latest_per_recipient.aggregate(
            success=Count("pk", filter=Q(event__in=list(SUCCESSFUL_EVENTS))),
            processing=Count("pk", filter=Q(event__in=list(INFO_EVENTS))),
            failed=Count("pk", filter=Q(event__in=failed_events)),
            cancelled=Count("pk", filter=Q(event=_CANCELLED_EVENT)),
        )
        return (
            counts["success"],
            counts["processing"],
            counts["failed"],
            counts["cancelled"],
        )

from django.db import models

from pymissive.config import SUCCESSFUL_EVENTS, FAILED_EVENTS, INFO_EVENTS


class MissiveEventManager(models.Manager):
    """Manager for the MissiveEvent model."""

    def get_event_counts(self, missive=None, recipient=None):
        """Return (success_count, processing_count, failed_count) from last event per recipient.

        Missive-level events (``recipient_id`` is NULL, e.g. the ``REQUEST``
        event created by ``send_missive``) are intentionally excluded: the
        status is derived from the latest event of each *recipient*. Without
        this filter a fully-delivered missive ends up as ``PARTIALLY_SUCCESS``
        because the missive-level ``request`` event is counted as a phantom
        "in-progress" recipient.
        """
        qs = self.filter(event__isnull=False, recipient__isnull=False)
        if missive is not None:
            qs = qs.filter(missive=missive)
        if recipient is not None:
            qs = qs.filter(recipient=recipient)
        qs = qs.order_by("recipient_id", "-occurred_at")
        by_recipient = {}
        for ev in qs:
            key = ev.recipient_id
            if key not in by_recipient:
                by_recipient[key] = ev.event
        success_count = sum(1 for e in by_recipient.values() if e in SUCCESSFUL_EVENTS)
        processing_count = sum(1 for e in by_recipient.values() if e in INFO_EVENTS)
        failed_count = sum(1 for e in by_recipient.values() if e in FAILED_EVENTS)
        return success_count, processing_count, failed_count

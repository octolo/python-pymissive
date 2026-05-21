"""MissiveEvent model for tracking missive events."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .mixins import CommentTimestampedModel
from .choices import MissiveEventType
from ..managers.event import MissiveEventManager
from django.utils import timezone
from ..fields import JSONField


class MissiveEvent(CommentTimestampedModel):
    """Event tracking for missives (status changes, webhooks, etc.)."""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiveevent",
        verbose_name=_("Missive"),
        help_text=_("Missive associated with this event"),
        blank=True,
        null=True,
        editable=False,
    )

    recipient = models.ForeignKey(
        "django_pymissive.MissiveRecipient",
        on_delete=models.CASCADE,
        related_name="to_recipientevent",
        verbose_name=_("Recipient"),
        help_text=_("Recipient associated with this event"),
        blank=True,
        null=True,
        editable=False,
    )

    event = models.CharField(
        max_length=50,
        choices=MissiveEventType.choices,
        null=True,
        blank=True,
        verbose_name=_("Event"),
        help_text=_("Event type (sent, delivered, read, failed, etc.)"),
    )

    reason = models.TextField(
        blank=True,
        verbose_name=_("Reason"),
        help_text=_("Reason or details about this event (provider-specific)"),
    )

    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )

    trace = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Trace"),
        help_text=_("Raw trace data (webhook payload, API response, etc.)"),
    )

    client_initiated = models.BooleanField(
        default=False,
        verbose_name=_("Client Initiated"),
        help_text=_(
            "True if the event was initiated by django_pymissive (send, resend, cancel, batch, etc.), "
            "False if received from a provider webhook."
        ),
    )

    occurred_at = models.DateTimeField(
        verbose_name=_("Occurred At"),
        help_text=_("When this event occurred"),
    )

    objects = MissiveEventManager()

    class Meta:
        verbose_name = _("Event")
        verbose_name_plural = _("Events")
        ordering = ["-occurred_at",]

    def get_reason(self):
        """Return human-readable reason for event from config, or empty string."""
        return MissiveEventType.get_description(self.event)

    def save(self, *args, **kwargs):
        if not self.occurred_at:
            self.occurred_at = timezone.now()
        if not self.reason and self.event:
            self.reason = self.get_reason()
        super().save(*args, **kwargs)

    def __str__(self):
        missive_ref = self.missive_id or "?"
        return f"{missive_ref} - {self.event} ({self.occurred_at})"

    def can_replay(self):
        """Return True if the event can be replayed."""
        return (self.missive_id and not self.client_initiated)

    def replay(self):
        """Replay the event. Uses trace["raw"] (normalized event) stored at creation."""
        if not self.missive_id:
            raise ValueError("Cannot replay event without associated missive")



        event = self.trace.get("raw") or self.trace
        if not isinstance(event, dict):
            raise ValueError("No replayable event in trace")
        event = dict(event)
        event["pk"] = self.pk
        self.missive.handle_events([event])

"""MissiveEvent model for tracking missive events."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .choices import MissiveEventType
from ..managers.event import MissiveEventManager
from django.utils import timezone



class MissiveEvent(models.Model):
    """Event tracking for missives (status changes, webhooks, etc.)."""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missiveevent",
        verbose_name=_("Missive"),
        help_text=_("Missive associated with this event"),
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

    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Description or details about this event"),
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )

    trace = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Trace"),
        help_text=_("Raw trace data (webhook payload, API response, etc.)"),
    )

    user_action = models.BooleanField(
        default=False,
        verbose_name=_("User Action"),
        help_text=_("Indicates if the event was triggered by a user action"),
    )

    occurred_at = models.DateTimeField(
        verbose_name=_("Occurred At"),
        help_text=_("When this event occurred"),
    )

    is_billed = models.BooleanField(
        default=False,
        verbose_name=_("Billed"),
        help_text=_("Indicates if the missive has been billed"),
    )
    billing_amount = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("Billing Amount"),
        help_text=_("Amount billed for the missive"),
    )
    estimate_amount = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("Estimate Amount"),
        help_text=_("Estimated amount for the missive"),
    )

    objects = MissiveEventManager()

    class Meta:
        verbose_name = _("Event")
        verbose_name_plural = _("Events")
        ordering = ["-occurred_at"]

    def save(self, *args, **kwargs):
        if not self.occurred_at:
            self.occurred_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.missive} - {self.event} ({self.occurred_at})"

    def set_billed(self):
        """Get billing amount and estimate amount."""
        if self.billing_amount is not None:
            self.is_billed = True
        self.save(update_fields=["is_billed"])

    def replay(self):
        """Replay the event."""
        provider = self.missive.provider._provider
        config_name = f"status_{self.missive.missive_type}".lower()
        config = provider._default_services_cfg.get(config_name, {})
        event = self.missive.provider._provider.normalize(data=self.trace, config=config)
        if event:
            event["pk"] = self.pk
            from ..task.events import handle_events
            handle_events([event])
            self.missive.set_last_status()
"""MissiveBilling model for billing records."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .mixins import CommentTimestampedModel


class MissiveBilling(CommentTimestampedModel):
    """Billing record for a missive, optionally scoped to a recipient."""

    missive = models.ForeignKey(
        "django_pymissive.Missive",
        on_delete=models.CASCADE,
        related_name="to_missivebilling",
        verbose_name=_("Missive"),
        help_text=_("Missive associated with this billing record"),
    )

    recipient = models.ForeignKey(
        "django_pymissive.MissiveRecipient",
        on_delete=models.CASCADE,
        related_name="to_recipientbilling",
        verbose_name=_("Recipient"),
        help_text=_("Recipient when billing is per-recipient; null for missive-level billing"),
        blank=True,
        null=True,
    )

    billing_amount = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name=_("Billing Amount"),
        help_text=_("Amount billed for this missive or recipient"),
    )

    estimate_amount = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name=_("Estimate Amount"),
        help_text=_("Estimated amount before sending"),
    )

    is_billed = models.BooleanField(
        default=False,
        verbose_name=_("Billed"),
        help_text=_("Indicates if this record has been billed"),
    )

    currency = models.CharField(
        max_length=3,
        blank=True,
        null=True,
        verbose_name=_("Currency"),
        help_text=_("ISO 4217 currency code (e.g. EUR, USD)"),
    )

    invoice = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Invoice"),
        help_text=_("Invoice or billing details from the provider"),
    )

    trace = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("Trace"),
        help_text=_("Trace of the billing request"),
    )

    class Meta:
        verbose_name = _("Billing")
        verbose_name_plural = _("Billings")
        ordering = ["-created_at"]

    def __str__(self):
        if self.recipient_id:
            return f"{self.missive_id} / {self.recipient_id} - {self.billing_amount or 0}"
        return f"{self.missive_id} - {self.billing_amount or 0}"

"""Missive campaign models."""

import uuid

from django.conf import settings
from django.db import models
from django.template import Context, Template
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from ..managers.campaign import MissiveCampaignManager
from ..models.choices import MissiveStatus
from django_geoaddress.fields import GeoaddressField

BODY_FIELD = import_string(
    getattr(settings, "PYMISSIVE_RICHTEXT_FIELD", "django.db.models.TextField")
)

class MissiveCampaign(models.Model):
    """Campaign grouping missives for batch sending."""
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    subject = models.CharField(
        max_length=255,
        verbose_name=_("Subject"),
        help_text=_("Campaign subject"),
    )
    sender_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender name"),
        help_text=_("Campaign sender name"),
    )

    # Email
    sender_email = models.EmailField(
        verbose_name=_("Sender email"),
        help_text=_("Campaign sender email"),
        blank=True,
        null=True,
    )

    body = BODY_FIELD(
        blank=True,
        verbose_name=_("Body"),
        help_text=_("Campaign body"),
    )
    body_text = models.TextField(
        blank=True,
        verbose_name=_("Body text"),
        help_text=_("Campaign body text"),
    )

    # SMS
    body_sms = models.TextField(
        blank=True,
        verbose_name=_("Body SMS"),
        help_text=_("Campaign body SMS"),
    )

    # Postal
    sender_address = GeoaddressField(
        verbose_name=_("Sender address"),
        help_text=_("Campaign sender address"),
        blank=True,
        null=True,
    )
    body_postal = BODY_FIELD(
        blank=True,
        verbose_name=_("Body Postal"),
        help_text=_("Campaign body Postal"),
    )

    objects = MissiveCampaignManager()

    class Meta:
        verbose_name = _("Campaign")
        verbose_name_plural = _("Campaigns")
        ordering = []

    def __str__(self):
        return self.subject

    def campaign_context(self):
        """Context for template rendering."""
        return {}

    def body_compiled(self):
        """Render body (email HTML) with campaign context."""
        if not self.body:
            return ""
        from django.template import Context, Template
        return Template(str(self.body)).render(Context(self.campaign_context()))

    def body_text_compiled(self):
        """Render body_text (email plain text) with campaign context."""
        if not self.body_etxt:
            return ""
        from django.template import Context, Template
        return Template(str(self.body_etxt)).render(Context(self.campaign_context()))

    def body_postal_compiled(self):
        """Render body_postal with campaign context."""
        if not self.body_postal:
            return ""
        from django.template import Context, Template
        return Template(str(self.body_postal)).render(Context(self.campaign_context()))

    def start_campaign(self):
        """Start the campaign."""
        scheduled = self.to_missivecampaignsend.create(
            campaign=self,
            scheduled_send_date=timezone.now()
        )
        scheduled.start_scheduled_campaign()


class MissiveScheduledCampaign(models.Model):
    """Scheduled send for a campaign."""

    campaign = models.ForeignKey(
        MissiveCampaign,
        on_delete=models.CASCADE,
        related_name="to_missivecampaignsend",
        verbose_name=_("Campaign"),
        editable=False,
    )
    scheduled_send_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Scheduled send date"),
        help_text=_(
            "Scheduled send date for the campaign (leave blank for immediate sending)"
        ),
    )
    send_date = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Send date"),
        help_text=_("Actual send date for the campaign"),
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name=_("Ended at"),
        help_text=_("Actual ended date for the campaign"),
    )

    class Meta:
        verbose_name = _("Campaign send")
        verbose_name_plural = _("Campaign sends")
        ordering = ["-scheduled_send_date", "-ended_at", "-id"]

    def start_scheduled_campaign(self):
        """Start the scheduled campaign."""
        from ..task import get_campaign_backend
        backend = get_campaign_backend()
        backend.delay(self.id)

    def run_campaign(self):
        """Run the campaign."""
        missives = self.campaign.to_missive.filter(status=MissiveStatus.DRAFT)
        for missive in missives:
            missive.send_missive()

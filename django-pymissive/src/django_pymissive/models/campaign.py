"""Missive campaign models."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..managers.campaign import MissiveCampaignManager
from ..models.mixins import CommentTimestampedModel, ConfigMixin, ProcessorsMixin
from ..models.choices import MissiveStatus, MissivePriority, AcknowledgementLevel, MissiveDeliveryMode
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from ..fields import RichTextField


class MissiveCampaign(ConfigMixin, ProcessorsMixin, CommentTimestampedModel):
    """Campaign grouping missives for batch sending.

    Inherits :class:`~django_pymissive.models.mixins.ConfigMixin` (JSON
    ``additional_context`` / ``additional_config`` / ``metadata`` bags) and
    :class:`~django_pymissive.models.mixins.ProcessorsMixin` (body /
    first_document / attachment processor chains + their resolvers). The
    campaign acts as the "parent" tier in the missive cascade — see
    :meth:`Missive._parent_processors`.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    subject = models.TextField(
        verbose_name=_("Subject"),
        help_text=_("Campaign subject"),
    )
    description = RichTextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
        help_text=_("Campaign description (optional)"),
    )

    # Email
    acknowledgement_email = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        default=AcknowledgementLevel.BASIC_DELIVERY,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    sender_email_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender email name"),
        help_text=_("Campaign sender email name"),
        blank=True,
        null=True,
    )
    sender_email = models.EmailField(
        verbose_name=_("Sender email"),
        help_text=_("Campaign sender email"),
        blank=True,
        null=True,
    )
    reply_to_email_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Reply-To name"),
        help_text=_("Display name for reply-to address"),
    )
    reply_to_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Reply-To email"),
        help_text=_("Email address for replies"),
    )
    body_html = RichTextField(
        blank=True,
        verbose_name=_("Body HTML"),
        help_text=_("Campaign email HTML body"),
    )
    body_text = models.TextField(
        blank=True,
        verbose_name=_("Body text"),
        help_text=_("Campaign body text"),
    )

    # SMS
    sender_phone_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender phone name"),
        help_text=_("Campaign sender phone name"),
        blank=True,
        null=True,
    )
    sender_phone = PhoneNumberField(
        blank=True,
        null=True,
        verbose_name=_("Sender phone"),
        help_text=_("Phone number of the sender (used for SMS)"),
    )
    body_sms = models.TextField(
        blank=True,
        verbose_name=_("Body SMS"),
        help_text=_("Campaign body SMS"),
    )

    # Address / LRE
    sender_address_name = models.CharField(
        max_length=255,
        verbose_name=_("Sender address name"),
        help_text=_("Campaign sender address name"),
        blank=True,
        null=True,
    )
    sender_address = GeoaddressField(
        verbose_name=_("Sender address"),
        help_text=_("Campaign sender address"),
        blank=True,
        null=True,
    )
    reply_to_address_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address name"),
        help_text=_("Display name for reply-to address"),
    )
    reply_to_address = GeoaddressField(
        max_length=512,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address"),
        help_text=_("Postal address for replies"),
    )
    acknowledgement_lre = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        default=AcknowledgementLevel.BASIC_DELIVERY,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    delivery_mode_lre = models.CharField(
        max_length=50,
        choices=MissiveDeliveryMode.choices,
        default=MissiveDeliveryMode.NORMAL,
        verbose_name=_("Delivery Mode"),
        help_text=_("Delivery mode (economic, normal, premium, express)"),
    )
    priority_lre = models.CharField(
        max_length=20,
        choices=MissivePriority.choices,
        default=MissivePriority.NORMAL,
        verbose_name=_("Priority"),
        help_text=_("Priority level"),
    )
    first_document = RichTextField(
        blank=True,
        verbose_name=_("First Document"),
        help_text=_("First document content (HTML, converted to PDF for LRE)"),
    )

    objects = MissiveCampaignManager()
    # Plain manager for select_for_update (PostgreSQL rejects FOR UPDATE with GROUP BY)
    objects_plain = models.Manager()

    class Meta:
        verbose_name = _("Campaign")
        verbose_name_plural = _("Campaigns")
        ordering = ["-created_at", "subject"]

    def __str__(self):
        return self.subject

    def get_browser_preview_path(self, *, preview_kind: str = "email") -> str:
        """Relative URL for the staff preview of this campaign.

        ``preview_kind`` selects which template will be rendered server-side
        (email, sms, postal — see ``PreviewView``). Returns ``""`` for an
        unsaved campaign.
        """
        if not self.pk:
            return ""
        return (
            reverse("django_pymissive:preview", args=["campaign", self.pk])
            + f"?type={preview_kind}"
        )

    @property
    def email_reply_to(self):
        """Reply-to dict for email; None when no reply address."""
        if not self.reply_to_email:
            return None
        return {
            "name": self.reply_to_email_name or "",
            "email": str(self.reply_to_email),
        }

    @property
    def address_reply_to(self):
        return {
            "name": self.reply_to_address_name or "",
            "address": self.reply_to_address or "",
        }

    @property
    def phone_sender(self):
        return {
            "name": self.sender_phone_name or "",
            "phone": self.sender_phone or "",
        }

    @property
    def email_sender(self):
        return {
            "name": self.sender_email_name or "",
            "email": self.sender_email or "",
        }

    @property
    def address_sender(self):
        return {
            "name": self.sender_address_name or "",
            "address": self.sender_address or "",
        }

    @property
    def attachments(self):
        """Campaign-level attachments (ATTACHMENT + VIRTUAL_ATTACHMENT)."""
        from .choices import MissiveAttachmentType
        from django.db.models import Q
        return self.to_campaigndocument.filter(
            Q(attachment_type=MissiveAttachmentType.ATTACHMENT)
            | Q(attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT),
        )

    def get_progress_path(self) -> str:
        """Relative URL for the live progress page of this campaign."""
        if not self.pk:
            return ""
        return reverse("django_pymissive:campaign_progress", args=[self.pk])

    def get_absolute_url(self):
        """Used by Django admin "View on site"."""
        return self.get_progress_path()

    def progress_payload(self) -> dict:
        """JSON-serializable progress snapshot for the campaign front page."""
        from django.db.models import Count, Q
        from pymissive.config import MISSIVE_TYPES
        from ..managers.scheduler import ERROR_STATUSES
        from ..models.choices import MissiveStatus

        rows = self.to_missive.values("missive_type").annotate(
            total=Count("id"),
            sent=Count("id", filter=~Q(status=MissiveStatus.DRAFT)),
            error=Count("id", filter=Q(status__in=ERROR_STATUSES)),
        )

        by_type: dict = {}
        total_count = sent_count = error_count = 0

        for row in rows:
            mtype = row["missive_type"]
            total = row["total"]
            sent = row["sent"]
            error = row["error"]
            total_count += total
            sent_count += sent
            error_count += error
            by_type[mtype] = {
                "label": MISSIVE_TYPES.get(mtype, mtype),
                "total": total,
                "sent": sent,
                "error": error,
                "progress": round(sent / total * 100) if total else 0,
            }

        progress = round(sent_count / total_count * 100) if total_count else 0
        is_processing = bool((self.metadata or {}).get("processing"))

        if is_processing:
            status = "running"
        elif total_count and not self.to_missive.filter(status=MissiveStatus.DRAFT).exists():
            status = "completed"
        else:
            status = "pending"

        runs = []
        for run in self.to_missivecampaignsend.order_by("-created_at")[:10]:
            runs.append({
                "id": run.id,
                "scheduled_send_date": (
                    run.scheduled_send_date.isoformat() if run.scheduled_send_date else None
                ),
                "send_date": run.send_date.isoformat() if run.send_date else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "status": run.run_status,
                "url": run.get_progress_path(),
            })

        return {
            "id": str(self.pk),
            "subject": self.subject,
            "running": is_processing,
            "status": status,
            "total_count": total_count,
            "sent_count": sent_count,
            "error_count": error_count,
            "progress": progress,
            "by_type": by_type,
            "runs": runs,
        }

    def start_campaign(self):
        """Start the campaign."""
        with transaction.atomic():
            campaign = MissiveCampaign.objects_plain.select_for_update().get(pk=self.pk)
            if campaign.metadata.get("processing"):
                raise ValidationError(_("Campaign is already being processed."))
            campaign.metadata = {**dict(campaign.metadata), "processing": True}
            campaign.save(update_fields=["metadata"])
            scheduled = campaign.to_missivecampaignsend.create(
                campaign=campaign,
                scheduled_send_date=timezone.now()
            )
            # Attach pending missives to this scheduler in bulk so the
            # live annotations (with_counts) can be derived from the FK.
            campaign.to_missive.filter(
                status=MissiveStatus.DRAFT,
                scheduler__isnull=True,
            ).update(scheduler=scheduled)
            scheduled.start_scheduled_campaign()

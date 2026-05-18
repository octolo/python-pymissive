"""Missive campaign models."""

import uuid

from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..managers.campaign import MissiveCampaignManager
from ..models.base import CommentTimestampedModel
from ..models.choices import MissiveStatus, MissivePriority, AcknowledgementLevel, MissiveDeliveryMode
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from ..fields import RichTextField, JSONField
from ..utils import get_base_url


class MissiveCampaign(CommentTimestampedModel):
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
    description = RichTextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Campaign description"),
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

    additional_context = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional context"),
        help_text=_("Additional context as JSON"),
    )
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )
    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )
    body_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Body processors"),
        help_text=_(
            "Ordered list of processors applied to compiled campaign body/"
            "first_document content. When non-empty, REPLACES the global "
            "defaults (PYMISSIVE_DEFAULT_BODY_PROCESSORS) — make sure to "
            "include django_template_processor here if you still want "
            "{{ var }} / {% tag %} rendering. A missive's own non-empty "
            "body_processors will in turn override these. Each entry may "
            "be a dotted path string, a [path, kwargs] pair, or a "
            "{\"processor\": path, \"kwargs\": {...}} dict."
        ),
    )
    first_document_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("First document PDF processors"),
        help_text=_(
            "Ordered list of processors used to build the first_document "
            "PDF for missives in this campaign. When non-empty, REPLACES "
            "the global defaults (PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS) "
            "— include django_pymissive.pdf_processors.weasyprint_renderer "
            "as the first entry if you still want the default HTML→PDF "
            "rendering. A missive's own non-empty first_document_processors "
            "will in turn override these. Each entry may be a dotted path "
            "string, a [path, kwargs] pair, or a {\"processor\": path, "
            "\"kwargs\": {...}} dict."
        ),
    )
    attachment_processors = JSONField(
        default=list,
        blank=True,
        verbose_name=_("Attachment processors"),
        help_text=_(
            "Ordered list of processors applied to every attachment of "
            "missives in this campaign right before sending. Each processor "
            "receives (missive, attachment, content_bytes) and returns new "
            "bytes. PDF-only processors (e.g. watermark_pdf_attachments) "
            "skip non-PDF attachments. When non-empty, REPLACES the global "
            "defaults (PYMISSIVE_DEFAULT_ATTACHMENT_PROCESSORS). A missive's "
            "own non-empty attachment_processors will in turn override these."
        ),
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

    def campaign_context(self):
        """Context for template rendering."""
        return {}

    @property
    def base_url(self):
        """Base URL for attachments and other needs. Uses get_base_url() from settings."""
        return get_base_url(trailing_slash=False)

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

    def get_default_body_processors(self):
        """Return default body processors (Django template rendering by default).

        Override on a subclass or set ``PYMISSIVE_DEFAULT_BODY_PROCESSORS = []``
        in Django settings to disable the default Django template rendering.
        """
        from ..body_processors import get_default_body_processors

        return get_default_body_processors()

    def get_body_processors(self):
        """Resolve which processors apply, "most specific wins" semantics.

        If ``self.body_processors`` is non-empty, those replace the defaults
        entirely; otherwise the defaults from
        :meth:`get_default_body_processors` are used. When overriding, make
        sure to include ``django_template_processor`` if you still want
        ``{{ var }}`` / ``{% tag %}`` rendering.
        """
        if self.body_processors:
            return list(self.body_processors)
        return self.get_default_body_processors()

    def get_default_pdf_processors(self):
        """Return the default PDF processor chain for ``first_document``.

        Honors ``PYMISSIVE_DEFAULT_FIRST_DOCUMENT_PROCESSORS`` from
        settings, otherwise falls back to a single
        :func:`~django_pymissive.pdf_processors.weasyprint_renderer`.
        """
        from ..pdf_processors import get_default_pdf_processors

        return get_default_pdf_processors()

    def get_first_document_processors(self):
        """Resolve the PDF processor chain at the campaign level.

        If ``self.first_document_processors`` is non-empty those replace
        the defaults entirely; otherwise the defaults from
        :meth:`get_default_pdf_processors` are used. Note that a missive's
        own non-empty ``first_document_processors`` always wins over this.
        """
        if self.first_document_processors:
            return list(self.first_document_processors)
        return self.get_default_pdf_processors()

    def get_default_attachment_processors(self):
        """Return default attachment processors (see Missive equivalent)."""
        from ..attachment_processors import get_default_attachment_processors

        return get_default_attachment_processors()

    def get_attachment_processors(self):
        """Resolve attachment processors at the campaign level.

        ``self.attachment_processors`` if non-empty, otherwise
        :meth:`get_default_attachment_processors`. A missive's own
        non-empty ``attachment_processors`` always wins over this.
        """
        if self.attachment_processors:
            return list(self.attachment_processors)
        return self.get_default_attachment_processors()

    def apply_body_processors(self, content: str, *, field_name: str | None = None) -> str:
        """Apply body processors (defaults + campaign) to ``content``."""
        from ..body_processors import apply_body_processors

        return apply_body_processors(
            content,
            self.get_body_processors(),
            campaign=self,
            field_name=field_name,
            context=self.campaign_context(),
        )

    def _compile(self, raw, *, field_name: str | None = None) -> str:
        """Run the body processor pipeline on ``raw``.

        The default pipeline starts with the Django template processor
        (rendering against ``campaign_context()``), then applies
        campaign-level processors.
        """
        if not raw:
            return ""
        return self.apply_body_processors(str(raw), field_name=field_name)

    def body_html_compiled(self):
        """Render body HTML (email) with campaign context."""
        return self._compile(self.body_html, field_name="body_html")

    def body_text_compiled(self):
        """Render body_text (email plain text) with campaign context."""
        return self._compile(self.body_text, field_name="body_text")

    def body_sms_compiled(self):
        """Render body_sms (SMS) with campaign context."""
        return self._compile(self.body_sms, field_name="body_sms")

    def first_document_compiled(self):
        """Render first_document with campaign context."""
        return self._compile(self.first_document, field_name="first_document")

    @property
    def attachments(self):
        from .choices import MissiveAttachmentType
        from django.db.models import Q
        return self.to_campaigndocument.filter(
            Q(attachment_type=MissiveAttachmentType.ATTACHMENT)
            | Q(attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT),
        )

    @property
    def attachments_physical(self):
        return self.attachments.filter(linked=False)

    def get_serialized_attachments(self, linked=False):
        """Get the attachments of the campaign."""
        qs = self.attachments.filter(linked=linked)
        return [attachment.get_serialized_attachment(linked=linked) for attachment in qs]

    def start_campaign(self):
        """Start the campaign."""
        with transaction.atomic():
            campaign = MissiveCampaign.objects_plain.select_for_update().get(pk=self.pk)
            if campaign.metadata.get("processing"):
                from django.core.exceptions import ValidationError
                raise ValidationError(_("Campaign is already being processed."))
            campaign.metadata = {**dict(campaign.metadata), "processing": True}
            campaign.save(update_fields=["metadata"])
            scheduled = campaign.to_missivecampaignsend.create(
                campaign=campaign,
                scheduled_send_date=timezone.now()
            )
            scheduled.start_scheduled_campaign()


class MissiveScheduledCampaign(CommentTimestampedModel):
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
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
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

"""Main Missive model for multi-channel sending."""

import uuid
from typing import Optional
from django.db import transaction
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.template import Context, Template
from django_providerkit import ProviderField
from django.utils.safestring import mark_safe
from django.urls import reverse
from django_geoaddress.fields import GeoaddressField
from phonenumber_field.modelfields import PhoneNumberField
from django.conf import settings
from django.utils.module_loading import import_string
from .choices import (
    AcknowledgementLevel,
    MissiveSupport,
    MissiveEventType,
    MissivePriority,
    MissiveStatus,
    event_to_status,
    MissiveType,
    get_missive_support_from_type,
    MissiveRecipientType,
    MissiveAttachmentType,
    MissiveThreadType,
    MissiveDeliveryMode,
)
from ..managers import (
    MissiveManager,
    MissiveMessageManager,
    MissiveHistoryManager,
)
from ..models.base import CommentTimestampedModel
from ..fields import RichTextField, JSONField
from ..utils import get_base_url
from django.core import signing
from django.core.files.base import ContentFile


SEPARATOR = "\n--------------------------------\n"
ATTACHMENT_ICON = "&#128196;"
ATTACHMENT_STYLE = "text-decoration: none; font-size: 14px;"
ATTACHMENT_TPL_HTML = """<div>
    <a href='{url}' target='_blank' rel='noopener' style='{style}'>
        {icon}&nbsp;{name}
    </a>
</div>"""

PREVIEW_ICON = "&#127760;"
PREVIEW_STYLE = "text-decoration: none; font-size: 14px;"
PREVIEW_TPL_HTML = """<a href='{url}' target='_blank' rel='noopener' style='{style}'>
    {icon}&nbsp;{text}
</a>"""


class Missive(CommentTimestampedModel):
    """Multi-channel missive model (email, SMS, postal, WhatsApp, etc.)."""
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )
    campaign = models.ForeignKey(
        "django_pymissive.MissiveCampaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="to_missive",
        verbose_name=_("Campaign"),
        help_text=_("Optional campaign this missive belongs to"),
    )
    thread_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Thread"),
        help_text=_("Thread ID for the missive"),
        db_index=True,
    )
    thread_type = models.CharField(
        max_length=50,
        choices=MissiveThreadType.choices,
        default=MissiveThreadType.MISSIVE,
        verbose_name=_("Thread Type"),
        help_text=_("Type of thread (missive, message, history)"),
    )
    provider = ProviderField(
        package_name="pymissive",
        blank=True,
        verbose_name=_("Provider"),
        help_text=_("Provider used to send this missive"),
    )
    status = models.CharField(
        max_length=20,
        choices=MissiveStatus.choices,
        default=MissiveStatus.DRAFT,
        verbose_name=_("Status"),
        help_text=_("Current status of the missive"),
    )
    missive_support = models.CharField(
        max_length=50,
        choices=MissiveSupport.choices,
        verbose_name=_("Missive Support"),
        help_text=_("Support for the missive (email, SMS, postal, etc.)"),
        editable=False,
    )
    brand_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("Brand Name"),
        help_text=_("Brand name used to send this missive"),
    )
    missive_type = models.CharField(
        max_length=50,
        choices=MissiveType.choices,
        verbose_name=_("Missive Type"),
        help_text=_("Type of missive (email, SMS, postal, etc.)"),
    )
    acknowledgement = models.CharField(
        max_length=50,
        choices=AcknowledgementLevel.choices,
        blank=True,
        null=True,
        verbose_name=_("Acknowledgement Level"),
        help_text=_("Desired acknowledgement level for delivery proof"),
    )
    delivery_mode = models.CharField(
        max_length=50,
        choices=MissiveDeliveryMode.choices,
        blank=True,
        null=True,
        verbose_name=_("Delivery Mode"),
        help_text=_("Delivery mode (email, SMS, postal, etc.)"),
    )
    priority = models.CharField(
        max_length=20,
        choices=MissivePriority.choices,
        blank=True,
        null=True,
        verbose_name=_("Priority"),
        help_text=_("Priority level"),
    )
    subject = models.CharField(
        max_length=500,
        verbose_name=_("Subject"),
        help_text=_("Subject line (for email, SMS, etc.)"),
        blank=True,
        null=True,
    )

    body_html = RichTextField(
        blank=True,
        null=True,
        verbose_name=_("Body HTML"),
        help_text=_("HTML message body (email) or rich content (postal)"),
    )
    body_text = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Body Text"),
        help_text=_("Plain text version of the message"),
    )

    # Sender
    sender_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Sender name"),
        help_text=_("Display name of the sender"),
    )
    sender_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Sender email"),
        help_text=_("Email address of the sender"),
    )
    sender_phone = PhoneNumberField(
        blank=True,
        null=True,
        verbose_name=_("Sender phone"),
        help_text=_("Phone number of the sender (used for SMS)"),
    )
    sender_address = GeoaddressField(
        blank=True,
        null=True,
        verbose_name=_("Sender address"),
        help_text=_("Postal address of the sender"),
    )

    # Reply-To (email only)
    reply_to_name = models.CharField(
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
    reply_to_address = GeoaddressField(
        max_length=512,
        blank=True,
        null=True,
        verbose_name=_("Reply-To address"),
        help_text=_("Postal address for replies"),
    )
    additional_context = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional context"),
        help_text=_("Additional context as JSON"),
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        editable=False,
        verbose_name=_("External ID"),
        help_text=_("External identifier from the provider"),
    )
    metadata = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
        help_text=_("Additional metadata as JSON"),
    )
    additional_config = JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional configuration"),
        help_text=_("Additional configuration as JSON"),
    )
    webhook_url = models.URLField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Webhook URL"),
        help_text=_("Webhook URL for the missive"),
    )
    message_by = models.ForeignKey(
        "django_pymissive.MissiveRecipient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="to_missivemessageby",
        verbose_name=_("Reply by"),
        help_text=_("Recipient who sent this reply (for inbound exchanges)"),
    )

    objects = MissiveManager()

    class Meta:
        verbose_name = _("Missive")
        verbose_name_plural = _("Missives")
        ordering = ["-created_at"]

    def __str__(self):
        recipient = self.first_recipient or _("Unknown")
        return f"{self.missive_type} - {recipient} ({self.status})"

    def _ensure_default_provider(self):
        """Set provider from MissiveConfig if empty."""
        if self.provider or not self.missive_type:
            return
        from .config import MissiveConfig
        config = MissiveConfig.objects.filter(missive_type=self.missive_type).first()
        if config and config.default_provider:
            self.provider = config.default_provider

    def _ensure_missive_defaults(self):
        """Apply default values for support and delivery settings."""
        if self.can_be_modified:
            support = get_missive_support_from_type(self.missive_type)
            if support:
                self.missive_support = support
        # Leave empty when campaign assigned; get_serialized_data resolves via locally_or_campaign
        # Use campaign_id to avoid FK resolution issues when creating via API/viewset
        has_campaign = bool(self.campaign_id)
        if not self.acknowledgement and not has_campaign:
            self.acknowledgement = AcknowledgementLevel.BASIC_DELIVERY
        if not self.delivery_mode and not has_campaign:
            self.delivery_mode = MissiveDeliveryMode.NORMAL
        if not self.priority and not has_campaign:
            self.priority = MissivePriority.NORMAL

    def save(self, *args, **kwargs):
        """Save the missive with auto-filled defaults (provider, support, acknowledgement, etc.)."""
        self._ensure_default_provider()
        self._ensure_missive_defaults()
        super().save(*args, **kwargs)

    def has_service(self, service):
        service_name = f"{service}_{self.missive_type}".lower()
        if self.provider:
            return hasattr(self.provider._provider, service_name)

    @property
    def token_missive(self):
        data = {"id": str(self.id)}
        return signing.dumps(data)

    @property
    def can_be_modified(self):
        return not self.external_id

    @property
    def last_event_display(self):
        return dict(MissiveEventType.choices).get(self.last_event, self.last_event)

    # Campaign uses _postal for address support, _email for email, _phone for phone
    _SUPPORT_TO_CAMPAIGN_SUFFIX = {"address": "postal", "email": "email", "phone": "phone"}

    def get_locally_or_campaign_value(self, field, fallback=None):
        """Return value from self, else from campaign (field or field_{suffix})."""
        locally = getattr(self, field, fallback)
        if locally:
            return locally
        if not self.campaign:
            return fallback
        campaign_val = getattr(self.campaign, field, None)
        if campaign_val:
            return campaign_val
        support = (self.missive_support or "").lower()
        if support:
            suffix = self._SUPPORT_TO_CAMPAIGN_SUFFIX.get(support, support)
            campaign_val = getattr(self.campaign, f"{field}_{suffix}", None)
            if campaign_val:
                return campaign_val
        return fallback

    @property
    def sender(self):
        return self.get_sender()

    @property
    def reply_to(self):
        return self.get_reply_to()

    def get_sender(self):
        support = self.missive_support.lower()
        name = self.get_locally_or_campaign_value(f"sender_{support}_name", self.sender_name)
        sender = self.get_locally_or_campaign_value(f"sender_{support}", getattr(self, f"sender_{support}", None))
        sender = dict(sender) if support == "address" else str(sender) if sender else ""
        return {
            "name": name or "",
            support: sender,
        }

    def get_reply_to(self):
        """Return reply_to dict for provider (email only)."""
        support = self.missive_support.lower()
        name = self.get_locally_or_campaign_value(f"reply_to_{support}_name", self.reply_to_name)
        reply_to = self.get_locally_or_campaign_value(f"reply_to_{support}", getattr(self, f"reply_to_{support}", None))
        if reply_to:
            return {
                "name": name or "",
                support: str(reply_to),
            }
        return None

    def get_acknowledgement(self):
        return self.get_locally_or_campaign_value(
            "acknowledgement", fallback=AcknowledgementLevel.BASIC_DELIVERY
        )

    def get_delivery_mode(self):
        return self.get_locally_or_campaign_value(
            "delivery_mode", fallback=MissiveDeliveryMode.NORMAL
        )

    def get_priority(self):
        return self.get_locally_or_campaign_value(
            "priority", fallback=MissivePriority.NORMAL
        )

    def is_serializable_field(self, field):
        return (not field.is_relation
                and not field.many_to_many
                and not field.name.startswith("_"))

    def get_serialized_data(self):
        """Serialize missive data to a dictionary for provider calls."""
        from .recipient import MissiveRecipient

        missive_data = {}
        for field in self._meta.get_fields():
            if self.is_serializable_field(field):
                if hasattr(self, f"get_{field.name}"):
                    missive_data[field.name] = getattr(self, f"get_{field.name}")()
                elif hasattr(self, f"{field.name}_compiled"):
                    missive_data[field.name] = getattr(self, f"{field.name}_compiled")
                else:
                    missive_data[field.name] = getattr(self, field.name)
        missive_data["recipients"] = [
            recipient.get_serialized_data() for recipient in self.recipients
        ]
        if self.cc:
            missive_data["cc"] = [
                recipient.get_serialized_data() for recipient in self.cc
            ]
        if self.bcc:
            missive_data["bcc"] = [
                recipient.get_serialized_data() for recipient in self.bcc
            ]
        missive_data["sender"] = self.get_sender()
        missive_data["reply_to"] = self.get_reply_to()
        missive_data["attachments"] = self.get_serialized_attachments(linked=False)
        missive_data.update(self.additional_config)
        return missive_data

    def call_provider_service(self, service: str, **kwargs):
        """Call a provider service."""
        service_name = f"{service}_{self.missive_type}".lower()
        return self.provider.call_service(service_name,  **kwargs)

    #########################################################
    # Check methods
    #########################################################

    def can_send(self):
        if self.has_service("send") and (not self.external_id or self.status == MissiveStatus.DRAFT):
            service_method = f"check_{self.missive_type}"
            return getattr(self, service_method)() if hasattr(self, service_method) else True
        return False

    def can_resend(self):
        if self.has_service("send"):
            service_method = f"check_{self.missive_type}"
            return getattr(self, service_method)() if hasattr(self, service_method) else True
        return False

    def check_recipients(self):
        return self.recipients.filter(recipient_type=MissiveRecipientType.RECIPIENT).exists()

    def check_email(self):
        body_html = self.get_locally_or_campaign_value("body_html")
        body_text = self.get_locally_or_campaign_value("body_text")
        subject = self.get_locally_or_campaign_value("subject")
        body = body_html or body_text
        return self.check_recipients() and bool(body and body.strip()) and bool(subject and subject.strip())

    def check_sms(self):
        body = self.get_locally_or_campaign_value("body_sms", self.body_text)
        return self.check_recipients() and bool(body and body.strip())

    def check_postal(self):
        body = self.get_locally_or_campaign_value("body_postal", self.body_html)
        return self.check_recipients() and bool(body and body.strip())

    @property
    def show_preview_browser(self):
        """Show the preview browser."""
        url = reverse("django_pymissive:preview", args=["missive", self.pk])
        url = self.base_url + url
        data = {
            "url": url,
            "icon": PREVIEW_ICON,
            "text": _("Preview in browser"),
            "style": PREVIEW_STYLE,
        }
        return mark_safe(PREVIEW_TPL_HTML.format(**data))  # nosec B703 B308

    @property
    def show_preview_browser_text(self):
        """Show the preview browser text."""
        url = reverse("django_pymissive:preview", args=["missive", self.pk])
        url = self.base_url + url
        return f"- {_('Preview in browser')}:{SEPARATOR}{url}\n"

    def missive_context(self):
        """Get the context of the missive."""
        context = getattr(self.campaign, "additional_context", {})
        context.update(self.additional_context or {})
        context.update({
            "show_preview_browser": self.show_preview_browser,
            "show_preview_browser_text": self.show_preview_browser_text,
            "show_attachments_linked": self.show_attachments_linked,
            "show_attachments_linked_text": self.show_attachments_linked_text,
        })
        return context

    def body_to_pdf(self):
        """Convert the body to PDF."""
        from django.utils.module_loading import import_string
        from django.conf import settings
        pdg_generator = getattr(settings, "MISSIVEPDF_GENERATOR", "django_pymissive.pdf.body_to_pdf")
        pdf = import_string(pdg_generator)(self)
        return pdf

    def generate_postal_first_page(self):
        """Generate first page PDF from body and save as attachment with priority 1."""
        from ..models.attachment import MissiveBaseAttachment

        pdf_bytes = self.body_to_pdf()
        filename = f"first-page-{self.thread_id}.pdf"
        # FileField stores full path; filter by path containing the filename
        existing = self.to_missiveattachment.filter(attachment_file__icontains=f"first-page-{self.thread_id}").first()
        if existing:
            existing.attachment_file.delete(save=False)
            existing.attachment_file.save(filename, ContentFile(pdf_bytes), save=True)
            return existing
        # Create then update priority (save() auto-sets priority for new attachments)
        att = MissiveBaseAttachment.objects.create(
            missive=self,
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            attachment_file=ContentFile(pdf_bytes, name=filename),
            priority=1,
            linked=False,
        )
        return att

    @property
    def subject_compiled(self):
        """Compile the subject of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("subject")
        return Template(tpl).render(Context(context))

    @property
    def body_html_compiled(self):
        """Compile the HTML body of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("body_html")
        return Template(tpl).render(Context(context))

    @property
    def body_text_compiled(self):
        """Compile the body text of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("body_text")
        return Template(tpl).render(Context(context))

    @property
    def body_sms_compiled(self):
        """Compile the body SMS of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("body_sms", self.body_text)
        return Template(tpl).render(Context(context))

    @property
    def body_postal_compiled(self):
        """Compile the body postal of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("body_postal", self.body_html)
        return Template(tpl).render(Context(context))

    #########################################################
    # Attachments
    #########################################################

    @property
    def base_url(self):
        """Base URL for attachments and other needs. Uses get_base_url() from settings."""
        return get_base_url(trailing_slash=False)

    @property
    def show_attachments_linked(self):
        """Show the attachments linked."""
        html = "<div>"
        for attachment in self.get_serialized_attachments(linked=True):
            data = {
                "url": attachment["url"],
                "icon": ATTACHMENT_ICON,
                "name": attachment["name"],
                "style": ATTACHMENT_STYLE,
            }
            html += ATTACHMENT_TPL_HTML.format(**data)
        html += "</div>"
        return mark_safe(html)  # nosec B703 B308

    @property
    def show_attachments_linked_text(self):
        """Show the attachments linked text."""
        qs = self.get_serialized_attachments(linked=True)
        if not qs:
            return ""
        title = _("Attachments:")
        text = f"{title}{SEPARATOR}"
        for attachment in qs:
            text += (
                f"- {attachment['name']}\n{self.base_url}{attachment['url']}{SEPARATOR}"
            )
        return text

    @property
    def attachments(self):
        from .attachment import MissiveAttachment
        q_filter = models.Q(attachment_type=MissiveAttachmentType.ATTACHMENT) | models.Q(
            attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT
        )
        parent_q = models.Q(missive=self)
        if self.campaign_id:
            parent_q |= models.Q(campaign=self.campaign)
        return MissiveAttachment.objects.filter(parent_q, q_filter)

    @property
    def attachments_physical(self):
        return self.attachments.filter(linked=False)

    def get_serialized_attachments(self, linked=False):
        """Get the attachments of the missive."""
        if not linked and self.missive_type == MissiveType.POSTAL:
            self.generate_postal_first_page()
        return [a.get_serialized_attachment(linked=linked) for a in self.attachments.filter(linked=linked)]

    #########################################################
    # Services
    #########################################################

    @transaction.atomic
    def resend_missive(self):
        """Resend the missive."""
        if not self.can_resend():
            raise ValidationError(_("Missive cannot be resend"))
        new_missive = self.duplicate_missive(thread_type=MissiveThreadType.HISTORY, thread_id=self.thread_id)
        new_missive.send_missive()
        return new_missive

    def duplicate_attachments(self, new_missive, source_missive):
        """Copy attachments from source_missive to new_missive (excl. first-page)."""
        first_page = f"first-page-{source_missive.thread_id}"
        for attachment in source_missive.to_missiveattachment.exclude(
            attachment_file__icontains=first_page
        ):
            attachment.pk = None
            attachment.id = None
            attachment.external_id = None
            attachment.missive = new_missive
            attachment.save()

    def duplicate_recipients(self, new_missive, source_missive):
        """Copy recipients from source_missive to new_missive."""
        for recipient in source_missive.to_missiverecipient.all():
            recipient.pk = None
            recipient.id = None
            recipient.external_id = None
            recipient.missive = new_missive
            recipient.save()

    @transaction.atomic
    def duplicate_missive(self, thread_type=MissiveThreadType.MISSIVE, thread_id=None):
        """Duplicate the missive with its attachments and recipients."""
        # Preserve source before mutating (new_missive = self would overwrite self)
        ModelClass = type(self)
        source = ModelClass.objects.get(pk=self.pk)
        new_missive = ModelClass.objects.get(pk=self.pk)
        new_missive.pk = None
        new_missive.id = None
        new_missive.external_id = None
        new_missive.thread_id = thread_id or uuid.uuid4()
        new_missive.thread_type = thread_type
        new_missive.status = MissiveStatus.DRAFT
        new_missive.save()
        self.duplicate_attachments(new_missive, source)
        self.duplicate_recipients(new_missive, source)
        return new_missive

    def _update_recipients(self, recipients):
        for recipient in recipients:
            rec = self.to_missiverecipient.get(id=recipient.get("internal_id"))
            rec.external_id = recipient.get("external_id")
            rec.save(update_fields=["external_id"])

    def _update_attachments(self, attachments):
        for attachment in attachments:
            att = self.to_missiveattachment.get(id=attachment.get("internal_id"))
            att.external_id = attachment.get("external_id")
            att.save(update_fields=["external_id"])

    def prepare_missive(self):
        """Prepare the missive for sending."""
        response = self.call_provider_service("prepare", **self.get_serialized_data())
        response["user_action"] = True
        self.external_id = response.get("external_id")
        self.save(update_fields=["external_id"])
        self._update_recipients(response.get("recipients", []))

    def update_missive(self):
        """Update the missive."""
        response = self.call_provider_service("update", **self.get_serialized_data())
        response["user_action"] = True
        self._update_recipients(response.get("recipients", []))

    def send_missive(self):
        """Send the missive."""
        if not self.can_send():
            raise ValidationError(_("Missive cannot be sent"))
        self.status = MissiveStatus.PROCESSING
        response = self.call_provider_service("send", **self.get_serialized_data())
        response["user_action"] = True
        self._update_attachments(response.get("attachments", []))
        self.external_id = response.get("external_id")
        if self.external_id:
            self.external_id = response.get("external_id")
            self.save(update_fields=["external_id", "status"])
            self.handle_events([response])
        else:
            self.to_missiveevent.create(event=MissiveStatus.FAILED, trace=response.get("raw", {}), user_action=True)

    def handle_events(self, events: list | dict):
        from ..task.events import handle_events
        handle_events(events)

    def cancel_missive(self):
        """Cancel the missive."""
        response = self.call_provider_service("cancel", **self.get_serialized_data())
        if response.get("code") in [200, 204, 404]:
            self.status = MissiveStatus.CANCELLED
            self.save(update_fields=["status"])

    def status_missive(self):
        """Get the status of the missive."""
        from ..task.events import handle_events
        response = self.call_provider_service("status", **self.get_serialized_data())
        self.handle_events(response)

    def set_last_status(self):
        last_event = self.to_missiveevent.filter(event__isnull=False).order_by("-occurred_at").first()
        if last_event:
            status = event_to_status(last_event.event)
            if status != self.status:
                self.status = status
                self.save(update_fields=["status"])

    #########################################################
    # Billing
    #########################################################

    def billing_amount_missive(self):
        """Get the billing amount of the missive."""
        self.call_provider_service("billing_amount", **self.get_serialized_data())

    def estimate_amount_missive(self):
        """Get the estimate amount of the missive."""
        self.call_provider_service("estimate_amount", **self.get_serialized_data())

    def set_billed(self):
        """Set the billed status of the missive."""
        self.to_missiveevent.filter(billing_amount__gt=0).update(is_billed=True)

    #########################################################
    # Recipients
    #########################################################

    @property
    def recipients(self):
        return self.to_missiverecipient.filter(
            recipient_type=MissiveRecipientType.RECIPIENT
        )

    @property
    def first_recipient(self):
        try:
            return self.recipients.first()
        except ObjectDoesNotExist:
            return _("Unknown recipient")

    @property
    def cc(self):
        return self.to_missiverecipient.filter(recipient_type=MissiveRecipientType.CC)

    @property
    def bcc(self):
        return self.to_missiverecipient.filter(recipient_type=MissiveRecipientType.BCC)

    #########################################################
    # Clean methods
    #########################################################

    def clean(self):
        """Clean the missive."""
        clean_by_support = f"clean_support_{self.missive_support}".lower()
        if hasattr(self, clean_by_support):
            getattr(self, clean_by_support)()

    def clean_subject(self):
        if not self.subject and not self.campaign:
            raise ValidationError({
                "subject": _("Subject or Campaign is required"),
            })

    def clean_support_email(self):
        """Clean the missive for email support."""
        has_body_missive = (self.body_html or self.body_text)
        has_body_campaign = (self.campaign and (self.campaign.body_html or self.campaign.body_text))
        if not has_body_missive and not has_body_campaign:
            raise ValidationError({
                "body_html": _("Body or body text is required (in missive or campaign)"),
                "body_text": _("Body or body text is required (in missive or campaign)"),
            })

    def clean_support_phone(self):
        """Clean the missive for SMS support."""
        has_body_missive = self.body_text
        has_body_campaign = (self.campaign and self.campaign.body_sms)
        if not has_body_missive and not has_body_campaign:
            raise ValidationError({
                "body_text": _("Body text is required (in missive or campaign)"),
            })

    def clean_support_postal(self):
        """Clean the missive for postal support."""
        has_body_missive = (self.body_html or self.to_missiveattachment.all().exists())
        has_body_campaign = (self.campaign and self.campaign.to_campaigndocument.exists())
        if not has_body_missive and not has_body_campaign:
            raise ValidationError({
                "body_html": _("Body or attachments are required (in missive or campaign)"),
            })


class MissiveHistory(Missive):
    """Missive history model."""
    objects = MissiveHistoryManager()

    class Meta:
        proxy = True
        verbose_name = _("Missive History")
        verbose_name_plural = _("Missive Histories")
        ordering = ["-created_at"]


class MissiveMessage(Missive):
    """Missive message model."""
    objects = MissiveMessageManager()

    class Meta:
        proxy = True
        verbose_name = _("Missive Message")
        verbose_name_plural = _("Missive Messages")
        ordering = ["-created_at"]
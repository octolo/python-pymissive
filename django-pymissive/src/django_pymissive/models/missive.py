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
)
from ..managers import (
    MissiveManager,
    MissiveMessageManager,
    MissiveHistoryManager,
)
from ..models.base import CommentTimestampedModel
from ..fields import RichTextField, JSONField
from django.core import signing


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
    status = models.CharField(
        max_length=20,
        choices=MissiveStatus.choices,
        default=MissiveStatus.DRAFT,
        verbose_name=_("Status"),
        help_text=_("Current status of the missive"),
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

    body = RichTextField(
        blank=True,
        null=True,
        verbose_name=_("Body"),
        help_text=_("Message body/content"),
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
        recipient = self.first_recipient or "Unknown"
        return f"{self.missive_type} - {recipient} ({self.status})"

    def save(self, *args, **kwargs):
        if self.can_be_modified:
            support = get_missive_support_from_type(self.missive_type)
            if support:
                self.missive_support = support
        if not self.priority:
            self.priority = self.campaign.priority if self.campaign else MissivePriority.NORMAL
        if not self.acknowledgement:
            self.acknowledgement = self.campaign.acknowledgement if self.campaign else AcknowledgementLevel.BASIC_DELIVERY
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

    def get_locally_or_campaign_value(self, field, fallback=None):
        locally = getattr(self, field, fallback)
        if not locally and self.campaign and getattr(self.campaign, field):
            return getattr(self.campaign, field)
        return locally

    @property
    def sender(self):
        return self.get_sender()

    @property
    def reply_to(self):
        return self.get_reply_to()

    def get_sender(self):
        support = self.missive_support.lower()
        name = (
            self.get_locally_or_campaign_value(f"sender_{support}_name")
            or self.get_locally_or_campaign_value("sender_name")
        )
        sender = self.get_locally_or_campaign_value(f"sender_{support}", getattr(self, f"sender_{support}", None))
        return {
            "name": name or "",
            support: str(sender) if sender else "",
        }

    def get_reply_to(self):
        """Return reply_to dict for provider (email only)."""
        support = self.missive_support.lower()
        name = (
            self.get_locally_or_campaign_value(f"reply_to_{support}_name")
            or self.get_locally_or_campaign_value("reply_to_name")
        )
        reply_to = self.get_locally_or_campaign_value(f"reply_to_{support}", getattr(self, f"reply_to_{support}", None))
        if reply_to:
            return {
                "name": name or "",
                support: str(reply_to),
            }
        return None

    def get_serialized_data(self):
        """Serialize missive data to a dictionary for provider calls."""
        from .recipient import MissiveRecipient

        missive_data = {
            field.name: getattr(self, field.name)
            for field in self._meta.get_fields()
            if not field.is_relation
            and not field.many_to_many
            and not field.name.startswith("_")
            and field.name not in ["body", "body_text"]
        }
        missive_data["body"] = self.body_compiled
        missive_data["body_text"] = self.body_text_compiled
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
        if self.has_service("send") and not self.external_id:
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
        return self.check_recipients() and (self.body or self.body_text) and self.subject

    def check_sms(self):
        return self.check_recipients() and self.body_text

    def check_postal(self):
        return self.check_recipients() and self.body

    @property
    def show_preview_browser(self):
        """Show the preview browser."""
        url = reverse("django_pymissive:preview", args=["missive", self.pk])
        url = self.domain + url
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
        url = self.domain + url
        return f"- {_('Preview in browser')}:{SEPARATOR}{url}\n"

    def missive_context(self):
        """Get the context of the missive."""
        context = getattr(self.campaign, "additional_context", {})
        context.update(self.additional_context or {})
        context.update({
            "show_preview_browser": self.show_preview_browser,
            "show_preview_browser_text": self.show_preview_browser_text,
            "show_attahcments_linked": self.show_attachments_linked,
            "show_attachments_linked_text": self.show_attachments_linked_text,
        })
        return context

    @property
    def subject_compiled(self):
        """Compile the subject of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("subject")
        return Template(tpl).render(Context(context))

    @property
    def body_compiled(self):
        """Compile the body of the missive."""
        context = self.missive_context()
        tpl = self.get_locally_or_campaign_value("body")
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
        tpl = self.get_locally_or_campaign_value("body_postal", self.body)
        return Template(tpl).render(Context(context))

    #########################################################
    # Attachments
    #########################################################

    @property
    def domain(self):
        from django.conf import settings

        if settings.DEBUG:
            return "http://localhost:8000"
        return settings.DOMAIN

    @property
    def show_attachments_linked(self):
        """Show the attachments linked."""
        html = "<div>"
        for attachment in self.get_serialized_attachments(linked=True):
            data = {
                "url": self.domain + attachment["url"],
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
                f"- {attachment['name']}\n{self.domain}{attachment['url']}{SEPARATOR}"
            )
        return text

    @property
    def attachments(self):
        return self.to_missivedocument.filter(
            models.Q(attachment_type=MissiveAttachmentType.ATTACHMENT)
            | models.Q(attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT),
        )

    @property
    def attachments_physical(self):
        return self.attachments.filter(linked=False)

    def get_serialized_attachments(self, linked=False):
        """Get the attachments of the missive."""
        qs = self.attachments.filter(linked=linked)
        return [attachment.get_serialized_attachment(linked=linked) for attachment in qs]

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

    @transaction.atomic
    def duplicate_missive(self, thread_type=MissiveThreadType.MISSIVE, thread_id=None):
        """Duplicate the missive."""
        new_missive = self
        new_missive.pk = None
        new_missive.id = None
        new_missive.external_id = None
        new_missive.thread_id = thread_id or uuid.uuid4()
        new_missive.thread_type = thread_type
        new_missive.status = MissiveStatus.DRAFT
        new_missive.save()

        for recipient in self.to_missiverecipient.all():
            new_recipient = recipient
            new_recipient.pk = None
            new_recipient.id = None
            new_recipient.external_id = None
            new_recipient.missive = new_missive
            new_recipient.status = MissiveStatus.DRAFT
            new_recipient.sent_at = None
            new_recipient.delivered_at = None
            new_recipient.save()

        return new_missive

    def prepare_missive(self):
        """Prepare the missive for sending."""
        self.status = MissiveStatus.PROCESSING
        self.save()
        self.call_provider_service("prepare", **self.get_serialized_data())

    def send_missive(self):
        """Send the missive."""
        if not self.can_send():
            raise ValidationError(_("Missive cannot be sent"))
        self.status = MissiveStatus.PROCESSING
        response = self.call_provider_service("send", **self.get_serialized_data())
        response["user_action"] = True
        self.external_id = response.get("external_id")
        if self.external_id:
            self.external_id = response.get("external_id")
            self.save(update_fields=["external_id"])
            from ..task.events import handle_events
            handle_events([response])
        else:
            self.to_missiveevent.create(event=MissiveStatus.FAILED, trace=response.get("raw", {}), user_action=True)
        self.set_last_status()

    def cancel_missive(self):
        """Cancel the missive."""
        self.call_provider_service("cancel", **self.get_serialized_data())

    def status_missive(self):
        """Get the status of the missive."""
        from ..task.events import handle_events
        response = self.call_provider_service("status", **self.get_serialized_data())
        handle_events(response)
        self.set_last_status()

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
        has_body_missive = (self.body or self.body_text)
        has_body_campaign = (self.campaign and (self.campaign.body or self.campaign.body_text))
        if not has_body_missive and not has_body_campaign:
            raise ValidationError({
                "body": _("Body or body text is required (in missive or campaign)"),
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
        """Clean the missive for phone support."""
        has_body_missive = (self.body or self.to_missivedocument.all().exists())
        has_body_campaign = (self.campaign and self.campaign.to_campaigndocument.exists())
        if not has_body_missive and not has_body_campaign:
            raise ValidationError({
                "body": _("Body or attachments are required (in missive or campaign)"),
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
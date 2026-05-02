"""Main Missive model for multi-channel sending."""

import uuid
from django.db import transaction
from django.utils import timezone
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
    status_from_event_counts,
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
from ..dispatch_signals import (
    missive_post_duplicate,
    missive_post_send,
    missive_pre_duplicate,
    missive_pre_send,
)
from ..utils import get_base_url, build_webhook_url, get_default_domain, get_default_scheme
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
    """Multi-channel missive model (email, SMS, address/LRE, application, etc.)."""
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
        help_text=_("Support for the missive (email, phone, address, application)"),
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
        help_text=_("Type of missive (email, sms, lre, ere, etc.)"),
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
        help_text=_("Delivery mode (economic, normal, premium, express)"),
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
        help_text=_("HTML message body (email) or rich content (LRE)"),
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
        if not self.provider:
            return False
        return hasattr(self.provider._provider, service_name)

    def can_preview_missive(self):
        """True if the provider implements ``preview_<missive_type>`` (e.g. ``preview_lre``)."""
        if not self.missive_type:
            return False
        return self.has_service("preview")

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

    # Missive field → campaign field, per support type.
    # Only fields whose names differ need an entry; absent fields use the same name on campaign.
    _CAMPAIGN_FIELD_MAP: dict[str, dict[str, str]] = {
        "email": {
            "sender_name":    "sender_email_name",
            "reply_to_name":  "reply_to_email_name",
            "acknowledgement": "acknowledgement_email",
        },
        "phone": {
            "sender_name":    "sender_phone_name",
            "body_text":      "body_sms",
        },
        "address": {
            "sender_name":    "sender_address_name",
            "reply_to_name":  "reply_to_address_name",
            "acknowledgement": "acknowledgement_lre",
            "delivery_mode":  "delivery_mode_lre",
            "priority":       "priority_lre",
            "body_html":      "first_document",
        },
    }

    # Missive fields that may be inherited from the campaign, per support type.
    _CAMPAIGN_SOURCED_FIELDS: dict[str, list[str]] = {
        "email": [
            "subject", "body_html", "body_text",
            "acknowledgement",
            "sender_name", "sender_email",
            "reply_to_name", "reply_to_email",
        ],
        "phone": [
            "subject", "body_text",
            "sender_name", "sender_phone",
        ],
        "address": [
            "subject", "body_html", "body_text",
            "acknowledgement", "delivery_mode", "priority",
            "sender_name", "sender_address",
            "reply_to_name", "reply_to_address",
        ],
    }

    @classmethod
    def get_campaign_sourced_fields(cls, support) -> list[str]:
        """Return the missive field names that can be sourced from campaign for the given support."""
        return list(cls._CAMPAIGN_SOURCED_FIELDS.get((support or "").lower(), []))

    @property
    def campaign_sourced_field_names(self):
        """Field names that can be sourced from campaign (for set_locally_ifnull / clear)."""
        names = []
        for field in self.get_campaign_sourced_fields(self.missive_support):
            if field not in names and hasattr(self, field):
                names.append(field)
        return names + (["additional_context"] if self.campaign_id else [])

    def get_locally_or_campaign_value(self, field, fallback=None):
        """Return local field value if set, else look up the matching campaign field.

        The campaign field name is resolved via _CAMPAIGN_FIELD_MAP[support][field].
        If the field has no entry in the map for the current support, the same name is
        used on the campaign (identity mapping).
        """
        locally = getattr(self, field, None)
        if locally:
            return locally
        if not self.campaign:
            return fallback
        support = (self.missive_support or "").lower()
        campaign_field = self._CAMPAIGN_FIELD_MAP.get(support, {}).get(field, field)
        return getattr(self.campaign, campaign_field, None) or fallback

    def set_locally_ifnull(self):
        """Copy campaign values to local fields when null. Preserves content at send time
        so that if the campaign changes later, already-sent missives keep their content."""
        if not self.campaign_id:
            return
        support = (self.missive_support or "").lower()
        fields = self.get_campaign_sourced_fields(support)

        updates = []
        for field in fields:
            if not hasattr(self, field):
                continue
            local = getattr(self, field, None)
            val = self.get_locally_or_campaign_value(field, local)
            if not local and val:
                setattr(self, field, val)
                updates.append(field)

        if self.campaign.additional_context and not (self.additional_context or {}):
            self.additional_context = dict(self.campaign.additional_context)
            updates.append("additional_context")

        if updates:
            self.save(update_fields=updates)

    def clear_campaign_sourced_fields(self, missive):
        """Clear campaign-sourced fields on missive so they will be re-filled from campaign at send."""
        fields_to_clear = missive.campaign_sourced_field_names
        if not fields_to_clear:
            return
        for attr in fields_to_clear:
            if not hasattr(missive, attr):
                continue
            empty = {} if attr == "additional_context" else None
            setattr(missive, attr, empty)
        missive.save(update_fields=fields_to_clear)

    @property
    def sender(self):
        return self.get_sender()

    @property
    def reply_to(self):
        return self.get_reply_to()

    def get_sender(self):
        support = self.missive_support.lower()
        name = self.get_locally_or_campaign_value("sender_name")
        sender = self.get_locally_or_campaign_value(f"sender_{support}")
        sender = dict(sender) if support == "address" else str(sender) if sender else ""
        return {
            "name": name or "",
            support: sender,
        }

    def get_reply_to(self):
        """Return reply_to dict for provider (email only)."""
        support = self.missive_support.lower()
        name = self.get_locally_or_campaign_value("reply_to_name")
        reply_to = self.get_locally_or_campaign_value(f"reply_to_{support}")
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

    def get_webhook_url(self):
        scheme = get_default_scheme()
        domain = get_default_domain()
        base = f"{scheme}://{(domain or '').strip().lstrip('/')}"
        return build_webhook_url(base, self.provider._provider.name, self.missive_type)

    def is_serializable_field(self, field):
        return (not field.is_relation
                and not field.many_to_many
                and not field.name.startswith("_"))

    def get_serialized_data(self, attachments=True):
        """Serialize missive data to a dictionary for provider calls."""

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
        if attachments:
            missive_data["attachments"] = self.get_serialized_attachments(linked=False)
        missive_data["webhook_url"] = self.get_webhook_url()
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
        if self.additional_config.get("use_provider_template", False):
            return self.check_recipients()
        body_html = self.get_locally_or_campaign_value("body_html")
        body_text = self.get_locally_or_campaign_value("body_text")
        subject = self.get_locally_or_campaign_value("subject")
        body = body_html or body_text
        return self.check_recipients() and bool(body and body.strip()) and bool(subject and subject.strip())

    def check_sms(self):
        body = self.get_locally_or_campaign_value("body_text")
        return self.check_recipients() and bool(body and body.strip())

    def check_lre(self):
        body = self.get_locally_or_campaign_value("body_html")
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
        pdg_generator = getattr(settings, "MISSIVEPDF_GENERATOR", "django_pymissive.pdf.body_to_pdf")
        pdf = import_string(pdg_generator)(self)
        return pdf

    def generate_first_document(self):
        """Generate first document PDF from first_document/body_html and save as attachment."""
        from ..models.attachment import MissiveBaseAttachment

        pdf_bytes = self.body_to_pdf()
        filename = f"first-document-{self.thread_id}.pdf"
        existing = self.to_missiveattachment.filter(attachment_file__icontains=f"first-document-{self.thread_id}").first()
        if existing:
            existing.attachment_file.delete(save=False)
            existing.attachment_file.save(filename, ContentFile(pdf_bytes), save=True)
            return existing
        att = MissiveBaseAttachment.objects.create(
            missive=self,
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            attachment_file=ContentFile(pdf_bytes, name=filename),
            priority=0,
            linked=False,
        )
        return att

    def _compiled_template_value(self, raw) -> str:
        """Render ``raw`` with ``missive_context()``; empty or invalid template → empty string (preview-safe)."""
        if raw is None:
            return ""
        text = str(raw)
        if not text.strip():
            return ""
        try:
            return Template(text).render(Context(self.missive_context()))
        except Exception:
            return ""

    @property
    def subject_compiled(self):
        """Compile the subject of the missive."""
        return self._compiled_template_value(self.get_locally_or_campaign_value("subject"))

    @property
    def body_html_compiled(self):
        """Compile the HTML body of the missive."""
        return self._compiled_template_value(self.get_locally_or_campaign_value("body_html"))

    @property
    def body_text_compiled(self):
        """Compile the body text of the missive."""
        return self._compiled_template_value(self.get_locally_or_campaign_value("body_text"))

    @property
    def body_sms_compiled(self):
        """Compile the body SMS of the missive."""
        return self._compiled_template_value(self.get_locally_or_campaign_value("body_text") or "")

    @property
    def first_document_compiled(self):
        """Compile first_document (campaign) or fallback to body_html when no campaign."""
        return self._compiled_template_value(self.get_locally_or_campaign_value("body_html") or "")

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
        """Attachments from missive and campaign (when campaign_id is set)."""
        from .attachment import MissiveBaseAttachment
        q_filter = models.Q(attachment_type=MissiveAttachmentType.ATTACHMENT) | models.Q(
            attachment_type=MissiveAttachmentType.VIRTUAL_ATTACHMENT
        )
        parent_q = models.Q(missive=self)
        if self.campaign_id:
            parent_q |= models.Q(campaign=self.campaign)
        return MissiveBaseAttachment.objects.filter(parent_q, q_filter)

    @property
    def attachments_physical(self):
        return self.attachments.filter(linked=False)

    def get_serialized_attachments(self, linked=False):
        """Get the attachments of the missive."""
        if not linked and self.missive_type == MissiveType.LRE:
            self.generate_first_document()
        return [a.get_serialized_attachment(linked=linked) for a in self.attachments.filter(linked=linked)]

    #########################################################
    # Services
    #########################################################

    @transaction.atomic
    def resend_missive(self):
        """Resend the missive: original becomes HISTORY, new duplicate is MISSIVE and gets sent."""
        if not self.can_resend():
            raise ValidationError(_("Missive cannot be resend"))
        self.thread_type = MissiveThreadType.HISTORY
        self.save(update_fields=["thread_type"])
        new_missive = self.duplicate_missive(thread_type=MissiveThreadType.MISSIVE, thread_id=self.thread_id, resend=True)
        new_missive.send_missive(old_missive=self)
        return new_missive

    def duplicate_attachments(self, new_missive, source_missive):
        """Copy attachments from source_missive to new_missive (excl. first-page)."""
        first_doc_prefix = f"first-document-{source_missive.thread_id}"
        attachments = source_missive.attachments.filter(
            attachment_type=MissiveAttachmentType.ATTACHMENT,
            missive=source_missive
        ).exclude(priority=0)
        for index, attachment in enumerate(attachments):
            attachment.pk = None
            attachment.id = None
            attachment.external_id = None
            attachment.missive = new_missive
            attachment.priority = index + 1
            attachment.save()

    def duplicate_recipients(self, new_missive, source_missive):
        """Copy recipients from source_missive to new_missive."""
        for recipient in source_missive.to_missiverecipient.all():
            recipient.pk = None
            recipient.id = None
            recipient.external_id = None
            recipient.missive = new_missive
            recipient.save()

    def duplicate_related_objects(self, new_missive, source_missive):
        """Copy related objects (e.g. contact links) from source_missive to new_missive."""
        for rel_obj in source_missive.to_missiverelatedobject.all():
            rel_obj.pk = None
            rel_obj.id = None
            rel_obj.missive = new_missive
            rel_obj.save()

    @transaction.atomic
    def duplicate_missive(self, thread_type=MissiveThreadType.MISSIVE, thread_id=None, resend=False):
        """Duplicate the missive with its attachments, recipients and related objects."""
        # Preserve source before mutating (new_missive = self would overwrite self)
        ModelClass = type(self)
        source = ModelClass.objects.get(pk=self.pk)
        missive_pre_duplicate.send(
            sender=ModelClass,
            source_missive=source,
            resend=resend,
            thread_type=thread_type,
            thread_id=thread_id,
        )
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
        self.duplicate_related_objects(new_missive, source)
        if resend:
            self.clear_campaign_sourced_fields(new_missive)
        missive_post_duplicate.send(
            sender=ModelClass,
            source_missive=source,
            new_missive=new_missive,
            resend=resend,
        )
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
        """Prepare the missive for sending (calls provider create)."""
        response = self.call_provider_service("create", **self.get_serialized_data())
        response["client_initiated"] = True
        self.external_id = response.get("external_id")
        self.save(update_fields=["external_id"])
        self._update_recipients(response.get("recipients", []))

    def update_missive(self):
        """Update the missive."""
        response = self.call_provider_service("update", **self.get_serialized_data())
        response["client_initiated"] = True
        self._update_recipients(response.get("recipients", []))

    def send_missive(self, *, old_missive=None):
        """Send the missive.

        :param old_missive: When sending a duplicate after a resend, pass the previous missive
            row (typically HISTORY). None for a normal first send.
        """
        if not self.can_send():
            raise ValidationError(_("Missive cannot be sent"))
        missive_pre_send.send(sender=self.__class__, missive=self, old_missive=old_missive)
        self.set_locally_ifnull()
        self.status = MissiveStatus.PROCESSING
        occurred_at = timezone.now()
        response = self.call_provider_service("send", **self.get_serialized_data())
        response["client_initiated"] = True
        if response.get("recipients"):
            self._update_recipients(response.get("recipients"))
        if response.get("attachments"):
            self._update_attachments(response.get("attachments"))
        self._update_attachments(response.get("attachments", []))
        self.external_id = response.get("external_id")
        if self.external_id:
            self.external_id = response.get("external_id")
            self.save(update_fields=["external_id", "status"])
            self.to_missiveevent.create(
                event=MissiveEventType.REQUEST,
                trace=response,
                client_initiated=True,
                occurred_at=occurred_at,
            )
            events = response.get("events")
            if events:
                self.handle_events(events)
        else:
            self.to_missiveevent.create(
                event=MissiveEventType.ERROR,
                trace=response,
                client_initiated=True,
                occurred_at=occurred_at,
            )
        self.refresh_from_db()
        missive_post_send.send(sender=self.__class__, missive=self, old_missive=old_missive)

    def handle_events(self, events: list | dict):
        from ..events import handle_events
        handle_events(events, self.provider, self.missive_type)

    def cancel_missive(self):
        """Cancel the missive (provider ``cancel_*`` when available — not Maileva LRE)."""
        response = self.call_provider_service("cancel", **self.get_serialized_data(attachments=False))
        if response.get("code") in [200, 204, 404]:
            self.status = MissiveStatus.CANCELLED
            self.save(update_fields=["status"])

    def delete_missive(self):
        """Remove the sending on the provider (``delete_*``), regardless of submission state."""
        response = self.call_provider_service("delete", **self.get_serialized_data(attachments=False))
        if response.get("code") in [200, 204, 404]:
            self.status = MissiveStatus.CANCELLED
            self.save(update_fields=["status"])

    def retrieve_missive(self):
        """Retrieve the status of the missive from the provider."""
        response = self.call_provider_service("retrieve", **self.get_serialized_data(attachments=False))
        events = response.get("events")
        if events:
            self.handle_events(events)

    def set_status(self):
        from ..models.event import MissiveEvent

        success_count, processing_count, failed_count = MissiveEvent.objects.get_event_counts(missive=self)
        status = status_from_event_counts(success_count, processing_count, failed_count)
        if status != self.status:
            self.status = status
            self.save(update_fields=["status"])

    #########################################################
    # Billing
    #########################################################

    def can_billings(self):
        return self.has_service("get_billings") and self.external_id

    def get_billings(self):
        """Get the billings of the missive."""
        if self.can_billings():
            from ..billings import handle_billings
            handle_billings(**self.get_serialized_data(attachments=False))

    def set_billed(self):
        """Set the billed status on billing records for this missive."""
        self.to_missivebilling.filter(billing_amount__gt=0).update(is_billed=True)

    #########################################################
    # Proofs
    #########################################################

    def can_proofs(self):
        """Return True if provider supports get_proofs for this missive type."""
        return self

    def get_proofs(self):
        """Get proofs (filename, url) from provider. Returns [] if not supported."""
        if not self.can_proofs():
            return []
        provider = self.provider._provider
        service_name = f"retrieve_proofs_{self.missive_type}"
        if not hasattr(provider, service_name):
            return []
        return provider.call_service_formatted(
            service_name, **self.get_serialized_data(attachments=False)
        )

    def download_proof(self, **kwargs):
        """Download the proof from the provider."""
        if not self.can_proofs():
            return None
        provider = self.provider._provider
        service_name = f"download_proof_{self.missive_type}"
        if not hasattr(provider, service_name):
            return None
        return provider.call_service_formatted(service_name, output_format="raw", **kwargs)

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

    # Fields that are required for sending per support type.
    # Each entry is either a single field name (any non-empty value suffices)
    # or a list of field names (at least one must be non-empty).
    _REQUIRED_FIELDS_BY_SUPPORT: dict[str, list] = {
        "email": [
            "subject",
            ["body_html", "body_text"],
            "sender_email",
        ],
        "phone": [
            "body_text",
        ],
        "address": [
            "sender_address",
        ],
    }

    def clean(self):
        """Validate the missive.

        Fields that can be inherited from campaign are nullable, but become required
        when no campaign is attached. Dispatches to clean_support_{support} for
        support-specific extra validation (e.g. attachments for LRE).
        """
        errors = {}
        support = (self.missive_support or "").lower()
        required = self._REQUIRED_FIELDS_BY_SUPPORT.get(support, [])

        for entry in required:
            if isinstance(entry, list):
                # At least one field in the group must be non-empty.
                if not any(self.get_locally_or_campaign_value(f) for f in entry):
                    msg = _("At least one of these fields is required (set locally or via campaign)")
                    for f in entry:
                        errors[f] = msg
            else:
                if not self.get_locally_or_campaign_value(entry):
                    errors[entry] = _("This field is required (set locally or via campaign)")

        if errors:
            raise ValidationError(errors)

        clean_by_support = f"clean_support_{support}"
        if hasattr(self, clean_by_support):
            getattr(self, clean_by_support)()

<<<<<<< HEAD
    def clean_subject(self):
        if not self.subject and not self.campaign:
            raise ValidationError({
                "subject": _("Subject or Campaign is required"),
            })

    def clean_support_email(self):
        """Clean the missive for email support."""
        if self.additional_config.get("use_provider_template", False):
            return True
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

=======
>>>>>>> 4e28e9c (Release pymissive and django-pymissive 1.0.9)
    def clean_support_address(self):
        """Extra validation for address (LRE) missives: body_html or attachments."""
        has_body = self.get_locally_or_campaign_value("body_html")
        has_attachments = self.pk and self.to_missiveattachment.all().exists()
        has_campaign_docs = self.campaign and self.campaign.to_campaigndocument.exists()
        if not has_body and not has_attachments and not has_campaign_docs:
            raise ValidationError({
                "body_html": _("Body or attachments are required (set locally or via campaign)"),
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

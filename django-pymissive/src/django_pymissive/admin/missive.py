"""Admin for Missive model."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from phonenumber_field.modelfields import PhoneNumberField
from phonenumber_field.formfields import SplitPhoneNumberField

from ..models.missive import Missive
from ..models.recipient import MissiveRecipient
from .recipient import (
    MissiveRecipientEmailInline,
    MissiveRecipientPhoneInline,
    MissiveRecipientAddressInline,
    MissiveRecipientNotificationInline,
)
from .document import MissiveAttachmentInline, MissiveVirtualAttachmentInline
from .event import MissiveEventInline
from .related_object import MissiveRelatedObjectInline
from ..models.choices import get_missive_style, MissiveStatus
from urllib.parse import unquote
from django.contrib import messages
from django.shortcuts import redirect



@admin.register(Missive)
class MissiveAdmin(AdminBoostModel):
    """Admin for missive model."""

    list_display = [
        "recipient_display",
        "sender_display",
        "provider_display",
        "campaign_display",
        "status_display",
        "event_display",
    ]
    list_filter = [
        "missive_type",
        "status",
        "priority",
        "is_billed",
        "provider",
        "created_at",
    ]
    search_fields = [
        "subject",
        "to_missiverecipient__name",
        "to_missiverecipient__email",
        "to_missiverecipient__phone",
        "to_missiverecipient__address",
        "external_id",
    ]
    readonly_fields = [
        "missive_support",
        "created_at",
        "updated_at",
        "sent_at",
        "delivered_at",
        "external_id",
        "buttons_show_and_preview",
    ]
    raw_id_fields = [
        "campaign",
    ]

    def get_readonly_fields(self, request, obj=None):
        """Make all fields readonly if missive has events."""
        readonly = list(super().get_readonly_fields(request, obj))

        if obj and obj.pk and obj.external_id:
            has_events = obj.to_missiveevent.exists()
            if has_events:
                all_fields = [
                    f.name
                    for f in self.model._meta.get_fields()
                    if (not f.is_relation or f.one_to_one) and f.name not in ["id"]
                ]
                readonly = list(set(readonly + all_fields))

        return readonly

    inlines = [
        MissiveRecipientEmailInline,
        MissiveRecipientPhoneInline,
        MissiveRecipientAddressInline,
        MissiveRecipientNotificationInline,
        MissiveAttachmentInline,
        MissiveVirtualAttachmentInline,
        MissiveEventInline,
        MissiveRelatedObjectInline,
    ]
    changeform_actions = {
        "prepare_missive": _("Prepare"),
        "send_missive": _("Send"),
        "cancel_missive": _("Cancel"),
        "status_missive": _("Status"),
        "billing_amount_missive": _("Billing Amount"),
        "estimate_amount_missive": _("Estimate Amount"),
        "duplicate_missive": _("Duplicate"),
    }

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            return SplitPhoneNumberField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def recipient_display(self, obj):
        recipient = obj.first_recipient
        if isinstance(recipient, MissiveRecipient):
            text = recipient.name
            if obj.count_target > 1:
                text += f" (+{obj.count_target - 1})"
            return self.format_with_help_text(text, recipient.target)
        return recipient

    recipient_display.short_description = _("Recipient")

    def sender_display(self, obj):
        sender = obj.sender
        if isinstance(sender, MissiveRecipient):
            return self.format_with_help_text(sender.name, sender.target)
        return sender

    sender_display.short_description = _("Sender")

    def provider_display(self, obj):
        return self.format_with_help_text(
            f"{obj.provider} ({obj.get_missive_type_display()})",
            obj.provider._provider.display_name,
        )

    provider_display.short_description = _("Provider")

    def status_display(self, obj):
        priority_style = get_missive_style(obj.priority)
        priority_html = self.format_label(
            obj.get_priority_display(), size="small", label_type=priority_style
        )
        status_style = get_missive_style(obj.status)
        status_html = self.format_label(
            obj.get_status_display(), size="small", label_type=status_style
        )
        if obj.last_event:
            event_style = get_missive_style(obj.last_event)
            event_html = self.format_label(
                obj.last_event_display, size="small", label_type=event_style
            )
            html = format_html("{} {} {}", priority_html, status_html, event_html)
        else:
            html = format_html("{} {}", priority_html, status_html)
        return self.format_with_help_text(html, obj.last_event_date)

    status_display.short_description = _("Status / Last Event Date")

    def button_show(self, obj):
        return format_html(
            '<a class="button" href="{}" target="_blank">{}</a>',
            reverse("django_pymissive:missive_preview", args=[obj.pk]),
            _("Show"),
        )

    def button_preview(self, obj):
        preview_url = reverse("django_pymissive:missive_preview_form")
        return format_html(
            '<button type="submit" form="missive_form" formaction="{}" formmethod="post" formtarget="_blank" class="button" name="_preview" style="margin-left: 10px;">{}</button>',
            preview_url,
            _("Preview"),
        )

    def buttons_show_and_preview(self, obj):
        buttons_html = []
        if obj.pk:
            buttons_html.append(self.button_show(obj))
        buttons_html.append(self.button_preview(obj))
        return mark_safe(" ".join(str(btn) for btn in buttons_html))  # nosec B703 B308

    buttons_show_and_preview.short_description = _("Show and Preview")

    def event_display(self, obj):
        event_related_html = format_html(
            "{} {}",
            self.format_label(f"{obj.count_event} event(s)", size="small"),
            self.format_label(
                f"{obj.count_related_object} related(s)",
                size="small",
                label_type="secondary",
            ),
        )
        return self.format_with_help_text(event_related_html, obj.subject)
    event_display.short_description = _("Event(s)/Related(s)/Subject")

    def campaign_display(self, obj):
        if obj.campaign is None:
            return "-"
        return self.format_with_help_text(
            self.format_label(obj.campaign.name, size="small"),
            obj.last_campaign_send_date)
    campaign_display.short_description = _("Campaign / Last Send Date")

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            None,
            [
                "campaign",
                "provider",
                "missive_support",
                "missive_type",
                "brand_name",
                "acknowledgement",
                "status",
                "priority",
            ],
        )
        self.add_to_fieldset(
            _("Billing"),
            ["is_billed", "billing_amount", "estimate_amount"],
        )
        self.add_to_fieldset(
            _("Content"),
            ["subject", "body", "body_text", "buttons_show_and_preview"],
        )
        self.add_to_fieldset(
            _("Tracking"),
            ["webhook_url", "external_id", "metadata"],
        )
        self.add_to_fieldset(
            _("Timestamps"),
            ["created_at", "updated_at", "sent_at", "delivered_at"],
        )
        self.add_to_fieldset(
            _("Billing"),
            ["is_billed"],
        )

    def provider_has_service(self, obj, service):
        service_name = f"{service}_{obj.missive_type}".lower()
        return hasattr(obj.provider._provider, service_name)

    def has_prepare_missive_permission(self, request, obj=None):
        return obj and obj.pk and self.provider_has_service(obj, "prepare")

    def handle_prepare_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.prepare_missive()
        messages.success(request, _("Missive prepared successfully."))

    def has_send_missive_permission(self, request, obj=None):
        return obj and obj.can_send()

    def handle_send_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.send_missive()
        messages.success(request, _("Missive sent successfully."))

    def has_cancel_missive_permission(self, request, obj=None):
        return obj and obj.pk and self.provider_has_service(obj, "cancel")

    def handle_cancel_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.cancel_missive()
        messages.success(request, _("Missive cancelled successfully."))

    def has_status_missive_permission(self, request, obj=None):
        return obj and obj.pk and self.provider_has_service(obj, "status") and obj.external_id

    def handle_status_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.status_missive()
        messages.success(request, _("Missive status updated successfully."))

    def has_duplicate_missive_permission(self, request, obj=None):
        return obj and obj.pk

    def handle_duplicate_missive(self, request, object_id):
        """Duplicate a missive by creating a copy."""
        object_id = unquote(object_id)
        missive = self.get_object(request, object_id)
        recipients = missive.to_missiverecipient.all()
        missive.pk = None
        missive.id = None
        missive.external_id = None
        missive.status = MissiveStatus.DRAFT
        missive.save()

        for recipient in recipients:
            recipient.pk = None
            recipient.id = None
            recipient.external_id = None
            recipient.missive = missive
            recipient.status = MissiveStatus.DRAFT
            recipient.save()

        messages.success(request, _("Missive duplicated successfully."))
        return redirect(reverse("admin:django_pymissive_missive_change", args=[missive.pk]))

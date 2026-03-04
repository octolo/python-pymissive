"""Admin for Missive model."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from urllib.parse import unquote
from django.contrib import messages
from django.shortcuts import redirect
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
from .attachment import MissiveAttachmentInline, MissiveVirtualAttachmentInline
from .event import MissiveEventInline
from .related_object import MissiveRelatedObjectInline
from ..models.choices import get_missive_style, MissiveStatus


class IsBillableListFilter(admin.SimpleListFilter):
    """Custom filter for is_billable annotation (not a model field)."""

    title = _("Is billable")
    parameter_name = "is_billable"

    def lookups(self, request, model_admin):
        return [
            ("1", _("Yes")),
            ("0", _("No")),
        ]

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(is_billable=True)
        if self.value() == "0":
            return queryset.filter(is_billable=False)
        return queryset


class IsBilledListFilter(admin.SimpleListFilter):
    """Custom filter for is_billed annotation (not a model field)."""

    title = _("Is billed")
    parameter_name = "is_billed"

    def lookups(self, request, model_admin):
        return [
            ("1", _("Yes")),
            ("0", _("No")),
        ]

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(is_billed=True)
        if self.value() == "0":
            return queryset.filter(is_billed=False)
        return queryset


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
        "billing_display",
    ]
    list_filter = [
        "missive_type",
        "status",
        "priority",
        IsBillableListFilter,
        IsBilledListFilter,
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
        "external_id",
        "buttons_show_and_preview",
        "external_id_display",
        "total_billed_amount_display",
        "total_billing_amount_display",
        "total_estimate_amount_display",
        "is_billable_display",
        "is_billed_display",
        "billing_display",
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
        "set_billed": _("Mark as paid"),
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
        return self.format_label(_("No recipient"), label_type="warning")

    recipient_display.short_description = _("Recipient")

    def billing_display(self, obj):
        tpl = self.boolean_icon_html(obj.is_billed)
        if obj.total_billed_amount is not None:
            tpl += "&nbsp;"
            label_type = "success" if obj.is_billed else "warning"
            tpl += self.format_label(f"{obj.total_billed_amount:.3f}", size="small", label_type=label_type)
        if obj.total_billing_amount is not None:
            tpl += "&nbsp;"
            label_type = "info" if obj.is_billed else "danger"
            tpl += self.format_label(f"{obj.total_billing_amount:.3f}", size="small", label_type=label_type)
        return mark_safe(tpl)

    def sender_display(self, obj):
        sender = obj.get_sender()
        name = sender["name"] or ""
        target = sender[obj.missive_support.lower()] or ""
        text = name or target or _("No sender")
        return self.format_with_help_text(text, target) if target else text

    sender_display.short_description = _("Sender")

    def external_id_display(self, obj):
        if not obj.external_id:
            return "-"
        return self.format_label(obj.external_id, size="large", label_type="success")
    
    external_id_display.short_description = _("External ID")

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
            reverse("django_pymissive:preview", args=["missive", obj.pk]),
            _("Show"),
        )

    def button_preview(self, obj):
        preview_url = reverse("django_pymissive:preview_form", args=["missive"])
        if obj.pk:
            preview_url = f"{preview_url}?pk={obj.pk}"
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
            self.format_label(obj.campaign.subject, size="small"),
            obj.last_campaign_send_date)
    campaign_display.short_description = _("Campaign / Last Send Date")

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            None,
            [

                "provider",
                "missive_type",
                "acknowledgement",
                "priority",
            ],
        )
        self.add_to_fieldset(
            _("Sender"),
            ["brand_name", "sender_name", "sender_email", "sender_phone", "sender_address"],
        )
        self.add_to_fieldset(
            _("Content"),
            ["subject", "body", "body_text", "buttons_show_and_preview"],
        )
        self.add_to_fieldset(
            _("Tracking"),
            ["campaign", "status", "webhook_url", "external_id_display", "missive_support", "additional_config", "metadata"],
        )
        self.add_to_fieldset(
            _("Timestamps"),
            ["created_at", "updated_at"],
        )
        self.add_to_fieldset(
            _("Billing"),
            [
                "total_billed_amount_display",
                "total_billing_amount_display",
                "total_estimate_amount_display",
                "is_billable_display",
                "is_billed_display",
            ],
        )

    def total_billed_amount_display(self, obj):
        if obj.total_billed_amount is None:
            return "-"
        label_type = "success" if obj.is_billed else "warning"
        return self.format_label(f"{obj.total_billed_amount:.3f}", size="small", label_type=label_type)
    total_billed_amount_display.short_description = _("Total Billed Amount")

    def total_billing_amount_display(self, obj):
        if obj.total_billing_amount is None:
            return "-"
        label_type = "info" if obj.is_billed else "danger"
        return self.format_label(f"{obj.total_billing_amount:.3f}", size="small", label_type=label_type)
    total_billing_amount_display.short_description = _("Total Billing Amount")

    def total_estimate_amount_display(self, obj):
        if obj.total_estimate_amount is None:
            return "-"
        return self.format_label(f"{obj.total_estimate_amount:.3f}", size="small", label_type="info")
    total_estimate_amount_display.short_description = _("Total Estimate Amount")

    def is_billable_display(self, obj):
        return obj.is_billable
    is_billable_display.short_description = _("Is billable")
    is_billable_display.boolean = True

    def is_billed_display(self, obj):
        return obj.is_billed
    is_billed_display.short_description = _("Is Billed")
    is_billed_display.boolean = True

    def provider_has_service(self, obj, service):
        service_name = f"{service}_{obj.missive_type}".lower()
        if obj.provider:
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
            recipient.sent_at = None
            recipient.delivered_at = None
            recipient.save()

        messages.success(request, _("Missive duplicated successfully."))
        return redirect(reverse("admin:django_pymissive_missive_change", args=[missive.pk]))

    def has_set_billed_permission(self, request, obj=None):
        return obj and obj.is_billable

    def handle_set_billed(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.set_billed()
        messages.success(request, _("Missive marked as paid successfully."))
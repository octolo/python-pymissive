"""Admin for Missive model."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from django_boosted import AdminBoostModel
from urllib.parse import unquote
from django.contrib import messages
from django.shortcuts import redirect
from phonenumber_field.modelfields import PhoneNumberField
from phonenumber_field.formfields import SplitPhoneNumberField
from urllib.parse import urlencode
from ..models.missive import Missive, MissiveMessage, MissiveHistory
from ..models.recipient import MissiveRecipient
from .recipient import (
    MissiveRecipientEmailInline,
    MissiveRecipientPhoneInline,
    MissiveRecipientAddressInline,
    MissiveRecipientNotificationInline,
)
from .attachment import (
    MissiveAttachmentInline,
    MissiveVirtualAttachmentInline,
)
from ..models.attachment import MissiveBaseAttachment
from ..utils import recalculate_attachment_priorities
from .event import MissiveEventInline
from .related_object import MissiveRelatedObjectInline
from ..models.choices import get_missive_style, MissiveStatus, MissiveThreadType
from django_boosted import admin_boost_view, admin_boost_action

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


class HistoryOrMessageListFilter(admin.SimpleListFilter):
    """Custom filter for history_or_message annotation (not a model field)."""

    title = _("Thread Type")
    parameter_name = "thread_type"

    def lookups(self, request, model_admin):
        return [
            ("history", _("History")),
            ("message", _("Message")),
            ("all", _("All")),
        ]

    def choices(self, changelist):
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": _("Missives"),
        }

        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }

    def queryset(self, request, queryset):
        if self.value() == "history":
            return queryset.filter(thread_type=MissiveThreadType.HISTORY)
        if self.value() == "message":
            return queryset.filter(thread_type=MissiveThreadType.MESSAGE)
        if self.value() == "all":
            return queryset
        return queryset.filter(thread_type=MissiveThreadType.MISSIVE)

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
        "thread_display",
        "billing_display",
    ]
    list_filter = [
        "missive_type",
        "status",
        "priority",
        IsBillableListFilter,
        IsBilledListFilter,
        HistoryOrMessageListFilter,
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
        "thread_display",
        "thread_id",
        "thread_type",
    ]
    raw_id_fields = [
        "campaign",
    ]
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

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model and issubclass(formset.model, MissiveBaseAttachment):
            self._recalculate_attachment_priorities(formset, form.instance)

    def _recalculate_attachment_priorities(self, formset, parent):
        """Recalculate attachment priorities after inline save (admin bypasses model save logic)."""
        recalculate_attachment_priorities(missive_id=parent.pk if parent else None)

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

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            return SplitPhoneNumberField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def recipient_display(self, obj):
        recipient = obj.first_recipient
        if isinstance(recipient, MissiveRecipient):
            text = recipient.name
            if obj.count_recipient > 1:
                text += f" (+{obj.count_recipient - 1})"
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
        if not obj.provider:
            return "-"
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

    def thread_display(self, obj):
        message = self.format_label(
            format_lazy(_("{} message(s)"), obj.count_message or 0),
            size="small",
            label_type="primary",
        )
        history = self.format_label(
            format_lazy(_("{} history(s)"), obj.count_history or 0),
            size="small",
            label_type="secondary",
        )
        thread_type = self.format_label(obj.get_thread_type_display(), size="small", label_type=get_missive_style(obj.thread_type))
        html = format_html("{} {} {}", thread_type, message, history)
        return self.format_with_help_text(html, str(obj.thread_id))

    thread_display.short_description = _("Message(s)/History(s)/Thread")

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
            self.format_label(
                format_lazy(_("{} event(s)"), obj.count_event),
                size="small",
            ),
            self.format_label(
                format_lazy(_("{} related(s)"), obj.count_related_object),
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
                "delivery_mode",
                "priority",
            ],
        )
        self.add_to_fieldset(
            _("Sender"),
            ["brand_name", "sender_name", "sender_email", "sender_phone", "sender_address"],
        )
        self.add_to_fieldset(
            _("Reply-To"),
            ["reply_to_name", "reply_to_email", "reply_to_address"],
        )
        self.add_to_fieldset(
            _("Content"),
            ["subject", "body_html", "body_text", "buttons_show_and_preview"],
        )
        self.add_to_fieldset(
            _("Tracking"),
            [
                "campaign", 
                "status",
                "webhook_url",
                "external_id_display",
                "missive_support",
                "thread_id",
                "thread_type",
            ],
        )
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"], classes=("wide", "collapse"))
        self.add_to_fieldset(
            _("Configs"),
            ["additional_context", "metadata", "additional_config"],
            classes=("wide", "collapse"),
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

    def is_draft(self, obj):
        return (obj and obj.pk and obj.status == MissiveStatus.DRAFT)

    def is_not_cancelled(self, obj):
        return (obj and obj.pk and obj.status != MissiveStatus.CANCELLED)

    def has_change_permission(self, request, obj=None):
        return self.is_not_cancelled(obj)

    def has_prepare_missive_permission(self, request, obj=None):
        return self.is_draft(obj) and self.provider_has_service(obj, "prepare") and not obj.external_id

    @admin_boost_action("prepare_missive", _("Prepare"))
    def handle_prepare_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.prepare_missive()
        messages.success(request, _("Missive prepared successfully."))

    def has_update_missive_permission(self, request, obj=None):
        return self.is_draft(obj) and self.provider_has_service(obj, "update")

    @admin_boost_action("update_missive", _("Update"))
    def handle_update_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.update_missive()
        messages.success(request, _("Missive updated successfully."))

    def has_resend_missive_permission(self, request, obj=None):
        return self.is_not_cancelled(obj) and obj.can_resend() and not self.is_draft(obj)

    @admin_boost_action("resend_missive", _("Resend"))
    def handle_resend_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        return redirect(reverse("admin:django_pymissive_missive_resend_missive", args=[obj.pk]))

    @admin_boost_view("confirm", _("Resend"), hidden=True)
    def resend_missive(self, request, obj, confirmed=False):
        if not confirmed:
            return {"confirm": _("Are you sure you want to resend this missive?")}  
        obj.resend_missive()
        messages.success(request, _("Missive resent successfully."))

    def has_send_missive_permission(self, request, obj=None):
        return self.is_draft(obj) and obj.can_send()

    @admin_boost_action("send_missive", _("Send"))
    def handle_send_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        return redirect(reverse("admin:django_pymissive_missive_send_missive", args=[obj.pk]))

    @admin_boost_view("confirm", _("Send"), hidden=True)
    def send_missive(self, request, obj, confirmed=False):
        if not confirmed:
            return {"confirm": _("Are you sure you want to send this missive?")}
        obj.send_missive()
        messages.success(request, _("Missive sent successfully."))
        return redirect(reverse("admin:django_pymissive_missive_change", args=[obj.pk]))

    def has_cancel_missive_permission(self, request, obj=None):
        return self.is_not_cancelled(obj) and self.provider_has_service(obj, "cancel") and obj.external_id

    @admin_boost_action("cancel_missive", _("Cancel"))
    def handle_cancel_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.cancel_missive()
        messages.success(request, _("Missive cancelled successfully."))

    def has_status_missive_permission(self, request, obj=None):
        return self.is_not_cancelled(obj) and self.provider_has_service(obj, "status") and obj.external_id

    @admin_boost_action("status_missive", _("Status"))
    def handle_status_missive(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.status_missive()
        messages.success(request, _("Missive status updated successfully."))

    def has_duplicate_missive_permission(self, request, obj=None):
        return obj and obj.pk

    @admin_boost_action("duplicate_missive", _("Duplicate"))
    def handle_duplicate_missive(self, request, object_id):
        """Duplicate a missive by creating a copy."""
        object_id = unquote(object_id)
        missive = self.get_object(request, object_id)
        new_missive = missive.duplicate_missive()
        messages.success(request, _("Missive duplicated successfully."))
        return redirect(reverse("admin:django_pymissive_missive_change", args=[new_missive.pk]))

    def has_set_billed_permission(self, request, obj=None):
        return obj and obj.is_billable

    @admin_boost_action("set_billed", _("Mark as paid"))
    def handle_set_billed(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.set_billed()
        messages.success(request, _("Missive marked as paid successfully."))

    @admin_boost_view("redirect", _("Show history"))
    def handle_history(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        data = {
            "thread_type": MissiveThreadType.HISTORY,
            "thread_id": obj.thread_id,
        }
        return url + "?" + urlencode(data)

    @admin_boost_view("redirect", _("Show message"))
    def handle_message(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        data = {
            "thread_type": MissiveThreadType.MESSAGE,
            "thread_id": obj.thread_id,
        }
        return url + "?" + urlencode(data)
    
"""Admin for Missive model."""

import json
import mimetypes

from django.contrib import admin
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from django_boosted import AdminBoostModel
from django.contrib.admin.utils import unquote as admin_unquote
from django.contrib import messages
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from phonenumber_field.modelfields import PhoneNumberField
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField
from phonenumber_field.formfields import SplitPhoneNumberField
from urllib.parse import urlencode
from django_geoaddress.fields import GeoaddressField
from ..forms.missive import RetrieveMissiveForm
from ..retrieve import retrieve_from_provider as do_retrieve_from_provider
from ..models.missive import Missive
from ..models.recipient import MissiveRecipient
from .recipient import (
    MissiveRecipientEmailInline,
    MissiveRecipientPhoneInline,
    MissiveRecipientAddressInline,
    MissiveRecipientApplicationInline,
    lock_geoaddress_formfield,
    missive_admin_locked,
)
from .attachment import (
    MissiveAttachmentBaseInline,
    MissiveProofInline,
)
from .permissions import ActionRightsMixin
from ..models.attachment import MissiveBaseAttachment
from ..utils import recalculate_attachment_priorities
from .event import MissiveEventInline
from .billing import MissiveBillingInline
from .related_object import MissiveRelatedObjectInline
from ..models.choices import get_missive_style, MissiveStatus, MissiveThreadType, MissiveSupport
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
class MissiveAdmin(ActionRightsMixin, AdminBoostModel):
    """Admin for missive model."""

    list_display = [
        "recipient_display",
        "sender_display",
        "provider_display",
        "campaign_display",
        "scheduler_display",
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
        "to_missiverecipient__external_id",
        "to_missiverecipient__substitute_id",
        "substitute_id",
    ]
    readonly_fields = [
        "missive_support",
        "created_at",
        "updated_at",
        "external_id",
        "external_id_display",
        "substitute_id",
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
        "scheduler",
    ]
    inlines = [
        MissiveRecipientEmailInline,
        MissiveRecipientPhoneInline,
        MissiveRecipientAddressInline,
        MissiveRecipientApplicationInline,
        MissiveAttachmentBaseInline,
        MissiveBillingInline,
        MissiveEventInline,
        MissiveRelatedObjectInline,
        MissiveProofInline,
    ]

    def get_queryset(self, request):
        """Annotate the counters the changelist and change form read."""
        return (
            super()
            .get_queryset(request)
            .select_related("campaign", "scheduler")
            .prefetch_related(Missive.objects.first_recipients_prefetch())
            .with_counts()
        )

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model and issubclass(formset.model, MissiveBaseAttachment):
            self._recalculate_attachment_priorities(formset, form.instance)

    def _recalculate_attachment_priorities(self, formset, parent):
        """Recalculate attachment priorities after inline save (admin bypasses model save logic)."""
        recalculate_attachment_priorities(missive_id=parent.pk if parent else None)

    def get_form(self, request, obj=None, change=False, **kwargs):
        self._lock_obj = obj
        return super().get_form(request, obj, change=change, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        """Lock fields on a sent/cancelled missive; GeoaddressField stays a widget."""
        readonly = list(super().get_readonly_fields(request, obj))
        if not missive_admin_locked(obj):
            return readonly
        geoaddress_names = {
            field.name
            for field in self.model._meta.get_fields()
            if isinstance(field, GeoaddressField)
        }
        for field in self.model._meta.get_fields():
            if (not field.is_relation or field.one_to_one) and field.name not in [
                "id",
                *geoaddress_names,
            ]:
                if field.name not in readonly:
                    readonly.append(field.name)
        return readonly

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            # Use standard PhoneNumberField for nullable fields: SplitPhoneNumberField
            # displays "None" when initial is None (django-phonenumber-field quirk)
            if db_field.null:
                return PhoneNumberFormField(**kwargs)
            return SplitPhoneNumberField(**kwargs)
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if isinstance(db_field, GeoaddressField) and missive_admin_locked(
            getattr(self, "_lock_obj", None)
        ):
            lock_geoaddress_formfield(formfield)
        return formfield

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if missive_admin_locked(obj):
            context["show_save"] = False
            context["show_save_and_continue"] = False
            context["show_save_and_add_another"] = False
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

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
        if obj.total_billed_amount is not None:
            label_type = "success" if obj.is_billed else "warning"
            return self.format_label(f"{obj.total_billed_amount:.3f}", size="small", label_type=label_type)
        if obj.total_billing_amount is not None:
            label_type = "info" if obj.is_billed else "danger"
            return self.format_label(f"{obj.total_billing_amount:.3f}", size="small", label_type=label_type)
        return "-"

    billing_display.short_description = _("Billing")

    def sender_display(self, obj):
        sender = obj.get_sender()
        name = sender["name"] or _("No sender name")
        if obj.missive_support == MissiveSupport.ADDRESS:
            target = obj.sender_address or ""
        else:
            target = sender[obj.missive_support.lower()] or ""
        if not name and not target:
            return self.format_label(_("No sender"), label_type="warning")
        return self.format_with_help_text(name, target)

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
            f"{obj.get_missive_type_display()}",
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
        html = format_html("{} {}", message, history)
        return self.format_with_help_text(html, obj.get_thread_type_display())

    thread_display.short_description = _("Message(s)/History(s)/Thread")

    @admin_boost_view("redirect", _("Preview"))
    def preview(self, request, obj):
        return obj.get_browser_preview_path()

    def has_preview_provider_confirm_permission(self, request, obj=None):
        """Draft missives whose provider implements ``preview_<missive_type>``."""
        return self.is_draft(obj) and obj.can_preview_missive()

    @admin_boost_view(
        "confirm",
        _("Preview (provider)")
    )
    def preview_provider_confirm(self, request, obj, confirmed=False):
        if obj.status != MissiveStatus.DRAFT:
            messages.warning(
                request,
                _(
                    "Provider preview is only available when the missive is in draft status."
                ),
            )
            return redirect(reverse("admin:django_pymissive_missive_change", args=[obj.pk]))
        if not obj.can_preview_missive():
            messages.warning(
                request,
                _("This provider does not implement preview for this missive type."),
            )
            return redirect(reverse("admin:django_pymissive_missive_change", args=[obj.pk]))
        if not confirmed:
            return {
                "confirm": _(
                    "Run provider preview? This calls the provider API "
                    "(e.g. preview_registered_letter on Maileva)."
                )
            }
        try:
            response = obj.call_provider_service(
                "preview", **obj.get_serialized_data()
            )
            preview_result = json.dumps(
                response
                if isinstance(response, (dict, list))
                else {"result": response},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect(reverse("admin:django_pymissive_missive_change", args=[obj.pk]))
        context = self.admin_site.each_context(request)
        opts = self.model._meta
        context.update(
            {
                "title": _("Provider preview result"),
                "opts": opts,
                "preview_result": preview_result,
                "object": obj,
                "original": obj,
                "original_url": reverse(
                    "admin:django_pymissive_missive_change", args=[obj.pk]
                ),
            }
        )
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "django_pymissive/admin/missive_provider_preview_result.html",
            context,
        )

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

    def scheduler_display(self, obj):
        if obj.scheduler_id is None:
            return "-"
        sched = obj.scheduler
        when = sched.send_date or sched.scheduled_send_date
        status_html = self.format_label(
            sched.run_status,
            size="small",
            label_type={"pending": "warning", "running": "info", "completed": "success"}.get(
                sched.run_status, "secondary"
            ),
        )
        return self.format_with_help_text(status_html, when)
    scheduler_display.short_description = _("Scheduler")

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
            ["subject", "body_rich", "body_text", "duplex_printing", "color_printing"],
        )
        self.add_to_fieldset(
            _("Tracking"),
            [
                "campaign",
                "scheduler",
                "status",
                "webhook_url",
                "external_id_display",
                "substitute_id",
                "missive_support",
                "thread_id",
                "thread_type",
            ],
        )
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"], classes=("wide", "collapse"))
        self.add_to_fieldset(
            _("Configs"),
            [
                "additional_context",
                "metadata",
                "additional_config",
                "body_processors",
                "first_document_processors",
                "attachment_processors",
            ],
            classes=("wide", "collapse"),
        )
        self.add_to_fieldset(
            _("Billing"),
            [
                "billing_display",
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
        from pymissive.config import provider_service_name

        service_name = provider_service_name(service, obj.missive_type)
        if obj.provider:
            return hasattr(obj.provider._provider, service_name)

    def get_boost_object_tools(self, request, object_id):
        items = []
        obj = self.get_object(request, admin_unquote(object_id)) if object_id else None
        opts = self.model._meta
        for view_name in self.get_boost_view_names():
            config = self.get_boost_view_config(view_name)
            if not config:
                continue
            if not config.get("requires_object", False):
                continue
            if not config.get("show_in_object_tools", True):
                continue
            perm_fn = getattr(self, f"has_{view_name}_permission", None)
            if callable(perm_fn) and not perm_fn(request, obj):
                continue
            url = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_{view_name}",
                args=[object_id],
                current_app=self.admin_site.name,
            )
            items.append({"label": config["label"], "url": url})
        return items

    def is_draft(self, obj):
        return (obj and obj.pk and obj.status == MissiveStatus.DRAFT)

    def is_not_cancelled(self, obj):
        return (obj and obj.pk and obj.status != MissiveStatus.CANCELLED)

    def has_change_permission(self, request, obj=None):
        # A locked missive is never editable, whatever rights the user has.
        if request.method == "POST" and missive_admin_locked(obj):
            return False
        # Deliberately skips AdminBoostModel, which returns True as soon as the
        # admin declares changeform actions — that is what gave every staff
        # account write access to every missive. Action buttons keep their own
        # has_<action>_permission gating.
        return admin.ModelAdmin.has_change_permission(self, request, obj)

    def has_prepare_missive_permission(self, request, obj=None):
        return (
            self.has_action_rights(request, obj)
            and self.is_draft(obj)
            and self.provider_has_service(obj, "create")
            and not obj.external_id
        )

    @admin_boost_action("prepare_missive", _("Prepare"))
    def handle_prepare_missive(self, request, object_id):
        self.call_object_method(
            request, object_id, "prepare_missive", _("Missive prepared successfully.")
        )

    def has_resend_missive_permission(self, request, obj=None):
        return (
            self.has_action_rights(request, obj)
            and self.is_not_cancelled(obj)
            and obj.can_resend()
            and not self.is_draft(obj)
            and obj.status != MissiveStatus.ERROR
        )

    @admin_boost_action("resend_missive", _("Resend"))
    def handle_resend_missive(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "resend_missive")

    @admin_boost_view("confirm", _("Resend"), hidden=True)
    def resend_missive(self, request, obj, confirmed=False):
        waiting = self.confirm_action(
            request, obj, confirmed, _("Are you sure you want to resend this missive?")
        )
        if waiting:
            return waiting
        new_missive = obj.resend_missive()
        new_missive.refresh_from_db()
        if new_missive.status == MissiveStatus.ERROR:
            messages.error(
                request,
                new_missive.last_send_error() or _("Missive send failed."),
            )
        else:
            messages.success(request, _("Missive resent successfully."))
        return self.redirect_to_change(new_missive)

    def has_send_missive_permission(self, request, obj=None):
        if not obj or not obj.pk:
            return False
        return (
            self.has_action_rights(request, obj)
            and obj.status in (MissiveStatus.DRAFT, MissiveStatus.ERROR)
            and obj.can_send()
        )

    @admin_boost_action("send_missive", _("Send"))
    def handle_send_missive(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "send_missive")

    @admin_boost_view("confirm", _("Send"), hidden=True)
    def send_missive(self, request, obj, confirmed=False):
        waiting = self.confirm_action(
            request, obj, confirmed, _("Are you sure you want to send this missive?")
        )
        if waiting:
            return waiting
        obj.send_missive()
        obj.refresh_from_db()
        if obj.status == MissiveStatus.ERROR:
            messages.error(request, obj.last_send_error() or _("Missive send failed."))
        else:
            messages.success(request, _("Missive sent successfully."))
        return self.redirect_to_change(obj)

    def has_cancel_missive_permission(self, request, obj=None):
        return (
            self.has_action_rights(request, obj)
            and self.is_not_cancelled(obj)
            and self.provider_has_service(obj, "cancel")
            and obj.external_id
        )

    @admin_boost_action("cancel_missive", _("Cancel"))
    def handle_cancel_missive(self, request, object_id):
        self.call_object_method(
            request, object_id, "cancel_missive", _("Missive cancelled successfully.")
        )

    def has_delete_missive_permission(self, request, obj=None):
        return bool(
            self.has_action_rights(request, obj)
            and obj
            and obj.pk
            and obj.external_id
            and self.provider_has_service(obj, "delete")
        )

    @admin_boost_action("delete_missive", _("Delete sending"))
    def handle_delete_missive(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "delete_missive")

    @admin_boost_view("confirm", _("Delete sending"), hidden=True)
    def delete_missive(self, request, obj, confirmed=False):
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _("Delete this sending on the provider? This cannot be undone."),
        )
        if waiting:
            return waiting
        obj.delete_missive()
        messages.success(request, _("Sending deleted on provider."))
        return self.redirect_to_change(obj)

    @admin_boost_view("adminform", _("Retrieve from provider"), requires_object=False)
    def retrieve_from_provider(self, request, form=None):
        """Create a missive from a provider partner ID or internal UID."""
        self.require_action_rights(request)
        if form is None:
            return {
                "form": RetrieveMissiveForm(),
                "save_label": _("Retrieve"),
                "has_change_permission": True,
            }
        try:
            missive, _created = do_retrieve_from_provider(
                provider=form.cleaned_data["provider"],
                missive_type=form.cleaned_data["missive_type"],
                partner_id=form.cleaned_data.get("partner_id"),
                uid=form.cleaned_data.get("uid"),
            )
        except Exception as exc:
            messages.error(request, str(exc))
            return {
                "form": form,
                "save_label": _("Retrieve"),
                "has_change_permission": True,
            }
        messages.success(request, _("Missive retrieved from provider."))
        return self.redirect_to_change(missive)

    def has_refresh_from_provider_permission(self, request, obj=None):
        return bool(
            self.has_action_rights(request, obj)
            and obj
            and obj.pk
            and self.provider_has_service(obj, "retrieve")
        )

    @admin_boost_view("confirm", _("Retrieve from provider"))
    def refresh_from_provider(self, request, obj, confirmed=False):
        """Update this missive from the provider using its uid and external_id."""
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _(
                "Retrieve this missive from the provider and replace local data "
                "(subject, body, sender, recipients, events, billings) "
                "only where the provider returns them? "
                "The missive external ID is kept."
            ),
        )
        if waiting:
            return waiting
        try:
            do_retrieve_from_provider(missive=obj)
        except Exception as exc:
            messages.error(request, str(exc))
            return self.redirect_to_change(obj)
        messages.success(request, _("Missive updated from provider."))
        return self.redirect_to_change(obj)

    def has_retrieve_missive_permission(self, request, obj=None):
        return (
            self.has_action_rights(request, obj)
            and self.is_not_cancelled(obj)
            and self.provider_has_service(obj, "retrieve")
            and obj.external_id
        )

    @admin_boost_action("retrieve_missive", _("Status"))
    def handle_retrieve_missive(self, request, object_id):
        self.call_object_method(
            request, object_id, "retrieve_missive", _("Missive status updated successfully.")
        )

    def has_retrieve_tracking_numbers_permission(self, request, obj=None):
        return bool(
            self.has_action_rights(request, obj) and obj and obj.can_tracking_numbers()
        )

    @admin_boost_action("retrieve_tracking_numbers", _("Tracking number"))
    def handle_retrieve_tracking_numbers(self, request, object_id):
        self.call_object_method(
            request,
            object_id,
            "retrieve_tracking_numbers",
            _("Tracking numbers updated successfully."),
        )

    def has_duplicate_missive_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk)

    @admin_boost_action("duplicate_missive", _("Duplicate"))
    def handle_duplicate_missive(self, request, object_id):
        missive = self.get_action_object(request, object_id)
        new_missive = missive.duplicate_missive()
        messages.success(request, _("Missive duplicated successfully."))
        return self.redirect_to_change(new_missive)

    def has_set_billed_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.is_billable)

    @admin_boost_action("set_billed", _("Mark as paid"))
    def handle_set_billed(self, request, object_id):
        self.call_object_method(
            request, object_id, "set_billed", _("Missive marked as paid successfully.")
        )

    def has_handle_history_permission(self, request, obj=None):
        return bool(obj and obj.pk and obj.count_history)

    @admin_boost_view("redirect", _("Show history"))
    def handle_history(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        data = {
            "thread_type": MissiveThreadType.HISTORY,
            "thread_id": obj.thread_id,
        }
        return url + "?" + urlencode(data)

    def has_handle_message_permission(self, request, obj=None):
        return bool(obj and obj.pk and obj.count_message)

    @admin_boost_view("redirect", _("Show conversation"))
    def handle_message(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        data = {
            "thread_type": MissiveThreadType.MESSAGE,
            "thread_id": obj.thread_id,
        }
        return url + "?" + urlencode(data)

    def has_handle_proofs_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.can_proofs())

    @admin_boost_view("message", _("Show proofs"))
    def handle_proofs(self, request, obj):
        """Display proofs as admin list (items: filename, url)."""
        self.require_action_rights(request, obj)
        proofs = obj.get_proofs()
        url_download = reverse("admin:django_pymissive_missive_download_proof", args=[obj.pk])
        csrf = get_token(request)
        # POST so a forged GET (img/src, prefetch) cannot spend provider quota.
        html_links = [
            format_html(
                '<div><form method="post" action="{}" target="_blank">'
                '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                '<input type="hidden" name="filename" value="{}">'
                '<button type="submit">{}</button>'
                '</form></div>',
                url_download,
                csrf,
                proof["filename"],
                proof["filename"],
            )
            for proof in proofs
        ]
        return {"message": mark_safe(" ".join(str(link) for link in html_links))}

    def has_download_proof_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.can_proofs())

    @admin_boost_view("message", _("Download proofs"), hidden=True)
    def download_proof(self, request, obj):
        if request.method != "POST":
            return HttpResponse(_("Method not allowed"), status=405)
        self.require_action_rights(request, obj)
        filename = request.POST.get("filename")
        if not filename:
            return HttpResponse(_("Missing filename"), status=400)
        # The provider URL is resolved server-side from the proof listing and is
        # never read from the body, so a forged url cannot be fetched.
        proof = next(
            (p for p in obj.get_proofs() if p.get("filename") == filename), None
        )
        if proof is None:
            return HttpResponse(_("Unknown proof"), status=404)
        content = obj.download_proof(**{
            "filename": filename,
            "url": proof["url"],
            "data": obj.get_serialized_data(attachments=False),
        })
        if content is None:
            messages.warning(request, _("Proof not available"))
            return self.redirect_to_change(obj)
        content_type, _encoding = mimetypes.guess_type(filename)
        response = HttpResponse(content, content_type=content_type or "application/octet-stream")
        response["Content-Disposition"] = 'attachment; filename="%s"' % filename.replace('"', '\\"')
        return response

    def has_save_proofs_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.can_proofs())

    @admin_boost_view("confirm", _("Save proofs"))
    def save_proofs(self, request, obj, confirmed=False):
        from django.core.files.base import ContentFile
        from ..models.choices import MissiveAttachmentType
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _("Download proofs from the provider and store them as attachments?"),
        )
        if waiting:
            return waiting
        proofs = obj.get_proofs()
        for proof in proofs:
            filename = proof["filename"]
            url = proof["url"]
            content = obj.download_proof(**{
                "filename": filename,
                "url": url,
                "data": obj.get_serialized_data(attachments=False),
            })
            if content is None:
                continue
            obj.to_missiveattachment.get_or_create(
                attachment_type=MissiveAttachmentType.PROOF,
                metadata__proof_filename=filename,
                defaults={
                    "attachment_file": ContentFile(content, name=filename),
                    "metadata": {"proof_filename": filename, "proof_url": url},
                    "linked": False,
                },
            )
        messages.success(request, _("Proofs saved successfully."))
        return self.redirect_to_change(obj)

    def has_get_billings_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.can_billings())

    @admin_boost_action("get_billings", _("Get billings"))
    def handle_get_billings(self, request, object_id):
        obj = self.call_object_method(
            request, object_id, "get_billings", _("Billings retrieved successfully.")
        )
        return self.redirect_to_change(obj)

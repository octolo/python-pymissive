"""Admin for MissiveBilling model."""

from django.contrib import admin
from django.contrib import messages
from django.http import StreamingHttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_boosted import AdminBoostModel, admin_boost_view

from ..billings import (
    billings_export_queryset,
    delay_retrieve_billings,
    iter_billings_csv,
    mark_billings_billed,
    retrieve_billings as do_retrieve_billings,
)
from ..forms.billing import BillingFilterForm, ExportBillingsForm, RetrieveBillingsForm
from ..models.billing import MissiveBilling


class MissiveBillingInline(admin.TabularInline):
    """Inline for billing records on missive."""

    model = MissiveBilling
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["recipient", "billing_amount", "estimate_amount", "currency", "is_billed", "invoice", "created_at"]
    raw_id_fields = ["recipient"]
    can_delete = True
    show_change_link = True
    readonly_fields = [
        "missive",
        "recipient",
        "billing_amount",
        "estimate_amount",
        "currency",
        "is_billed",
        "invoice",
        "created_at",
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MissiveBilling)
class MissiveBillingAdmin(AdminBoostModel):
    """Admin for billing records."""

    list_display = [
        "missive",
        "recipient",
        "billing_amount",
        "estimate_amount",
        "is_billed",
        "created_at",
    ]
    list_filter = [
        "missive__provider",
        "missive__missive_type",
        "is_billed"
    ]
    search_fields = [
        "missive__external_id",
        "missive__subject",
        "recipient__name",
        "recipient__email",
        "recipient__phone",
    ]
    raw_id_fields = ["missive", "recipient"]
    readonly_fields = ["created_at", "updated_at"]
    actions = ["set_billed"]

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "missive",
                    "recipient",
                    "billing_amount",
                    "estimate_amount",
                    "currency",
                    "invoice",
                    "is_billed",
                )
            },
        ),
    ]
    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"])

    @admin.action(description=_("Mark as billed"))
    def set_billed(self, request, queryset):
        updated = queryset.filter(billing_amount__gt=0).update(is_billed=True)
        self.message_user(request, _(f"{updated} record(s) marked as billed."))

    @admin_boost_view("adminform", _("Retrieve billings"), requires_object=False)
    def retrieve_billings(self, request, form=None):
        """Retrieve provider billings between two dates, optionally as a task."""
        if form is None:
            return {
                "form": RetrieveBillingsForm(),
                "save_label": _("Retrieve"),
                "has_change_permission": True,
            }
        payload = {
            "provider": form.cleaned_data["provider"],
            "missive_type": form.cleaned_data["missive_type"],
            "start_date": form.cleaned_data["start_date"],
            "end_date": form.cleaned_data["end_date"],
        }
        try:
            if form.cleaned_data.get("as_task"):
                delay_retrieve_billings(**payload)
                messages.info(request, _("Billing retrieval started."))
            else:
                do_retrieve_billings(**payload)
                messages.success(request, _("Billings retrieved from provider."))
        except Exception as exc:
            messages.error(request, str(exc))
            return {
                "form": form,
                "save_label": _("Retrieve"),
                "has_change_permission": True,
            }
        return redirect(reverse("admin:django_pymissive_missivebilling_changelist"))

    @admin_boost_view("adminform", _("Export CSV"), requires_object=False)
    def export_csv(self, request, form=None):
        """Export billings between two dates as a CSV download."""
        if form is None:
            return {
                "form": ExportBillingsForm(),
                "save_label": _("Export"),
                "has_change_permission": True,
            }
        queryset = billings_export_queryset(
            start_date=form.cleaned_data["start_date"],
            end_date=form.cleaned_data["end_date"],
            provider=form.cleaned_data.get("provider") or None,
            missive_type=form.cleaned_data.get("missive_type") or None,
        )
        start = form.cleaned_data["start_date"].isoformat()
        end = form.cleaned_data["end_date"].isoformat()
        extra_fields = form.cleaned_data.get("fields") or []
        one_row = bool(form.cleaned_data.get("one_row"))

        def stream():
            yield "\ufeff"
            yield from iter_billings_csv(
                queryset, extra_fields=extra_fields, one_row=one_row
            )

        response = StreamingHttpResponse(
            stream(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="billings_{start}_{end}.csv"'
        )
        return response

    @admin_boost_view("adminform", _("Mark as billed"), requires_object=False)
    def mark_billed(self, request, form=None):
        """Mark billings as billed between two dates."""
        if form is None:
            return {
                "form": BillingFilterForm(),
                "save_label": _("Mark as billed"),
                "has_change_permission": True,
            }
        updated = mark_billings_billed(
            start_date=form.cleaned_data["start_date"],
            end_date=form.cleaned_data["end_date"],
            provider=form.cleaned_data.get("provider") or None,
            missive_type=form.cleaned_data.get("missive_type") or None,
        )
        messages.success(
            request,
            _("{updated} record(s) marked as billed.").format(updated=updated),
        )
        return redirect(reverse("admin:django_pymissive_missivebilling_changelist"))

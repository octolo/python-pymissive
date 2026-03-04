"""Admin for MissiveEvent model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel, AdminBoostFormat
from urllib.parse import unquote
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.safestring import mark_safe

from ..models.event import MissiveEvent


class BaseMissiveEventAdmin(AdminBoostFormat):
    """Base admin for missive event model."""

    def billing_display(self, obj):
        """Display billing amount and estimate amount."""
        if not obj.user_action:
            return "-"
        tpl = self.boolean_icon_html(obj.is_billed)
        if obj.billing_amount is not None:
            tpl += "&nbsp;"
            tpl += self.format_label(f"{obj.billing_amount:.3f}", size="small", label_type="success" if obj.is_billed else "warning")
        if obj.estimate_amount is not None:
            tpl += "&nbsp;"
            tpl += self.format_label(f"{obj.estimate_amount:.3f}", size="small", label_type="info")
        return mark_safe(tpl)
    billing_display.short_description = _("Billing Amount")


class MissiveEventInline(admin.TabularInline, BaseMissiveEventAdmin):
    """Inline for missive events (read-only)."""

    model = MissiveEvent
    extra = 0
    readonly_fields = [
        "missive",
        "event",
        "recipient",
        "description",
        "occurred_at",
        "user_action",
        "billing_display",
    ]
    fields = [
        "missive",
        "recipient",
        "event",
        "description",
        "occurred_at",
        "user_action",
        "billing_display",
    ]
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MissiveEvent)
class MissiveEventAdmin(AdminBoostModel, BaseMissiveEventAdmin):
    """Admin for missive event model."""

    list_display = [
        "event",
        "missive",
        "recipient",
        "occurred_at",
        "user_action",
        "billing_display",
    ]
    list_filter = [
        "event",
    ]
    search_fields = [
        "event",
        "description",
        "missive__subject",
        "recipient__name",
        "recipient__email",
        "recipient__phone",
        "recipient__address",
    ]
    readonly_fields = [
        "missive",
        "recipient",
        "event",
        "description",
        "metadata",
        "trace",
        "occurred_at",
        "user_action",
        "billing_display",
    ]
    raw_id_fields = ["missive", "recipient"]
    changeform_actions = {
        "replay": _("Replay"),
        "set_billed": _("Mark as paid"),
    }

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "missive",
                    "recipient",
                    "event",
                    "description",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Details"),
            ["metadata", "occurred_at", "trace", "user_action"],
        )
        self.add_to_fieldset(
            _("Billing"),
            ["billing_amount", "estimate_amount", "is_billed"],
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_replay_permission(self, request, obj=None):
        return obj and obj.pk and obj.missive.pk and obj.trace

    def handle_replay(self, request, obj=None):
        """Handle replay of event."""
        obj = unquote(obj)
        obj = self.get_object(request, obj)
        obj.replay()
        messages.success(request, _("Event replayed successfully."))

    def handle_set_billed(self, request, obj=None):
        """Handle set billed of event."""
        obj = unquote(obj)
        obj = self.get_object(request, obj)
        obj.set_billed()
        messages.success(request, _("Billed status updated successfully."))
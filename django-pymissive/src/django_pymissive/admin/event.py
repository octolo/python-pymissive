"""Admin for MissiveEvent model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..models.event import MissiveEvent


class MissiveEventInline(admin.TabularInline):
    """Inline for missive events (read-only)."""

    model = MissiveEvent
    extra = 0
    readonly_fields = [
        "missive",
        "event",
        "recipient",
        "description",
        "occurred_at",
    ]
    fields = [
        "missive",
        "recipient",
        "event",
        "description",
        "occurred_at",
    ]
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MissiveEvent)
class MissiveEventAdmin(AdminBoostModel):
    """Admin for missive event model."""

    list_display = [
        "event",
        "missive",
        "recipient",
        "occurred_at",
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
    ]
    raw_id_fields = ["missive", "recipient"]

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
            ["metadata", "occurred_at", "trace"],
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

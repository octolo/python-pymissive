"""Admin for MissiveEvent model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from urllib.parse import unquote

from django.contrib import messages

from ..models.event import MissiveEvent

class UntreatedListFilter(admin.SimpleListFilter):
    """Custom filter for untreated events."""

    title = _("Untreated")
    parameter_name = "untreated"

    def lookups(self, request, model_admin):
        return [("1", _("Yes")), ("0", _("No"))]

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(missive__isnull=True)
        if self.value() == "0":
            return queryset.filter(missive__isnull=False)
        return queryset


class MissiveEventInline(admin.TabularInline):
    """Inline for missive events (read-only)."""

    model = MissiveEvent
    extra = 0
    readonly_fields = [
        "missive",
        "recipient",
        "event",
        "reason",
        "occurred_at",
        "client_initiated",
    ]
    fields = [
        "missive",
        "recipient",
        "event",
        "reason",
        "occurred_at",
        "client_initiated",
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
        "missive_provider",
        "occurred_at",
        "client_initiated",
    ]
    list_filter = [
        "event",
        "missive__provider",
        "client_initiated",
        UntreatedListFilter,
    ]
    search_fields = [
        "event",
        "reason",
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
        "reason",
        "metadata",
        "trace",
        "occurred_at",
        "client_initiated",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["missive", "recipient"]
    changeform_actions = {
        "replay": _("Replay"),
    }

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "missive",
                    "recipient",
                    "event",
                    "reason",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Details"),
            ["occurred_at", "trace", "client_initiated", "metadata",],
        )
        self.add_to_fieldset(_("Comment/Timestamps"), ["comment", "created_at", "updated_at"])

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_replay_permission(self, request, obj=None):
        return obj and obj.pk and obj.can_replay()

    @admin.display(ordering="missive__provider", description=_("Provider"))
    def missive_provider(self, obj):
        return obj.missive.provider if obj.missive_id else None

    def handle_replay(self, request, obj=None):
        """Handle replay of event."""
        obj = unquote(obj)
        obj = self.get_object(request, obj)
        obj.replay()
        messages.success(request, _("Event replayed successfully."))

"""Admin for MissiveCampaign model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from urllib.parse import unquote
from ..models.campaign import MissiveCampaign, MissiveScheduledCampaign
from django_boosted.decorators import admin_boost_view
from django.urls import reverse 


@admin.register(MissiveScheduledCampaign)
class MissiveScheduledCampaignAdmin(AdminBoostModel):
    """Admin for missive scheduled campaign model."""

    list_display = [
        "campaign",
        "scheduled_send_date",
        "send_date",
        "ended_at",
    ]
    readonly_fields = [
        "campaign",
        "scheduled_send_date",
        "send_date",
        "ended_at",
    ]


class MissiveScheduledCampaignInline(admin.TabularInline):
    """Inline for missive scheduled campaign model."""

    model = MissiveScheduledCampaign
    extra = 0
    readonly_fields = [
        "campaign",
        "send_date",
        "ended_at",
    ]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MissiveCampaign)
class MissiveCampaignAdmin(AdminBoostModel):
    """Admin for missive campaign model."""

    list_display = [
        "name",
        "stats_display",
        "last_send_date_display",
        "last_ended_at_display",
    ]
    search_fields = ["name", "description"]
    ordering = ["-id"]
    inlines = [MissiveScheduledCampaignInline]
    changeform_actions = {
        "start_campaign": _("Start Campaign"),
    }

    def stats_display(self, obj):
        """Display missive/recipient counts and status percentages."""
        parts = [
            f"{obj.count_missive} missive(s)",
            f"{obj.count_recipient} recipient(s)",
            f"{obj.pct_failed:.0f}% failed",
            f"{obj.pct_success:.0f}% success",
            f"{obj.pct_processing:.0f}% processing",
        ]
        return " | ".join(parts)

    stats_display.short_description = _("Stats")

    def last_send_date_display(self, obj):
        """Display last send date from annotated queryset."""
        return getattr(obj, "last_send_date", None) or "-"

    last_send_date_display.short_description = _("Last send date")

    def last_ended_at_display(self, obj):
        """Display last ended at from annotated queryset."""
        return getattr(obj, "last_ended_at", None) or "-"

    last_ended_at_display.short_description = _("Last ended at")

    def handle_start_campaign(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        obj.start_campaign()
        self.message_user(request, _("Campaign started successfully."))

    @admin_boost_view("redirect", "Show missives")
    def handle_show_missives(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        url += f"?campaign={obj.pk}"
        return url
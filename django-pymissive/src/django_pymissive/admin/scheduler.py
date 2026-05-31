"""Admin for MissiveScheduledCampaign model."""

from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.shortcuts import redirect
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view, admin_boost_action
from pymissive.config import MISSIVE_TYPES

from ..models.scheduler import MissiveScheduledCampaign


_SCHEDULED_CAMPAIGN_INLINE_FIELDSETS = (
    (
        None,
        {
            "fields": (
                "missive_type",
                "scheduled_send_date",
                "retry_failed",
            ),
        },
    ),
    (
        _("Tracking"),
        {
            "classes": ("collapse",),
            "fields": (
                "send_date",
                "ended_at",
            ),
        },
    ),
    (
        _("External task object"),
        {
            "classes": ("collapse",),
            "fields": (
                "external_task_backend",
                ("task_content_type", "task_object_id"),
                "task_object_arguments",
            ),
        },
    ),
    (
        _("Config"),
        {
            "classes": ("collapse",),
            "fields": ("additional_config",),
        },
    ),
)


@admin.register(MissiveScheduledCampaign)
class MissiveScheduledCampaignAdmin(AdminBoostModel):
    """Admin for missive scheduled campaign model."""

    view_on_site = True

    list_display = [
        "campaign",
        "missive_type",
        "scheduled_send_date",
        "send_date",
        "ended_at",
        "progress_display",
        "by_type_display",
        "task_object_display",
        "comment",
    ]
    list_filter = ["missive_type"]
    readonly_fields = [
        "campaign",
        "send_date",
        "ended_at",
        "progress_display",
        "by_type_display",
        "created_at",
        "updated_at",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and not obj.can_send:
            for field in ("missive_type", "scheduled_send_date", "external_task_backend",
                          "task_content_type", "task_object_id", "task_object_arguments",
                          "additional_config"):
                if field not in readonly:
                    readonly.append(field)
        return readonly

    def get_queryset(self, request):
        return super().get_queryset(request).with_counts()

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "campaign",
                    "missive_type",
                    "scheduled_send_date",
                    "retry_failed",
                    "send_date",
                    "ended_at",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        self.add_to_fieldset(
            _("Progress"),
            ["progress_display", "by_type_display"],
        )
        self.add_to_fieldset(
            _("External task object"),
            [
                "external_task_backend",
                "task_content_type",
                "task_object_id",
                "task_object_arguments",
            ],
            classes=("collapse",),
        )
        self.add_to_fieldset(
            _("Config / audit"),
            ["additional_config", "comment", "created_at", "updated_at"],
            classes=("collapse",),
        )

    changeform_actions = {
        "start_campaign": _("Start campaign"),
        "reschedule": _("Reschedule"),
        "duplicate": _("Duplicate"),
    }

    # -- permissions --

    def has_start_campaign_permission(self, request, obj=None):
        return bool(obj and obj.pk and obj.can_send)

    def has_reschedule_permission(self, request, obj=None):
        return bool(obj and obj.pk and not obj.can_send)

    def has_duplicate_permission(self, request, obj=None):
        return bool(obj and obj.pk)

    # -- actions --

    @admin_boost_action("start_campaign", _("Start campaign"))
    def handle_start_campaign(self, request, object_id):
        return redirect(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_start_campaign",
                args=[object_id],
            )
        )

    @admin_boost_view("confirm", _("Start campaign"), hidden=True)
    def start_campaign(self, request, obj, confirmed=False):
        if not obj.can_send:
            messages.error(
                request,
                _("This scheduled campaign cannot be started (already sent or not yet due)."),
            )
            return redirect(
                reverse("admin:django_pymissive_missivescheduledcampaign_change", args=[obj.pk])
            )
        if not confirmed:
            return {"confirm": _("Are you sure you want to start this scheduled campaign?")}
        obj.start_scheduled_campaign()
        messages.success(request, _("Scheduled campaign started successfully."))
        return redirect(reverse("admin:django_pymissive_missivescheduledcampaign_changelist"))

    @admin_boost_action("reschedule", _("Reschedule"))
    def handle_reschedule(self, request, object_id):
        return redirect(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_reschedule",
                args=[object_id],
            )
        )

    @admin_boost_view("confirm", _("Reschedule"), hidden=True)
    def reschedule(self, request, obj, confirmed=False):
        if not confirmed:
            return {"confirm": _("Create a new scheduled send now (duplicating this configuration)?")}
        new_scheduled = MissiveScheduledCampaign.objects.create(
            campaign=obj.campaign,
            scheduled_send_date=timezone.now(),
            missive_type=obj.missive_type,
            task_content_type=obj.task_content_type,
            task_object_id=obj.task_object_id,
            task_object_arguments=obj.task_object_arguments,
            external_task_backend=obj.external_task_backend,
            additional_config=obj.additional_config,
            comment=obj.comment,
        )
        messages.success(request, _("New scheduled send created."))
        return redirect(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_change",
                args=[new_scheduled.pk],
            )
        )

    @admin_boost_action("duplicate", _("Duplicate"))
    def handle_duplicate(self, request, object_id):
        return redirect(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_duplicate",
                args=[object_id],
            )
        )

    @admin_boost_view("confirm", _("Duplicate"), hidden=True)
    def duplicate(self, request, obj, confirmed=False):
        if not confirmed:
            return {"confirm": _("Duplicate this scheduled send? The copy will not be started automatically.")}
        new_scheduled = MissiveScheduledCampaign.objects.create(
            campaign=obj.campaign,
            scheduled_send_date=obj.scheduled_send_date,
            missive_type=obj.missive_type,
            task_content_type=obj.task_content_type,
            task_object_id=obj.task_object_id,
            task_object_arguments=obj.task_object_arguments,
            external_task_backend=obj.external_task_backend,
            additional_config=obj.additional_config,
            comment=obj.comment,
        )
        messages.success(request, _("Scheduled send duplicated — you can edit it before starting."))
        return redirect(
            reverse(
                "admin:django_pymissive_missivescheduledcampaign_change",
                args=[new_scheduled.pk],
            )
        )

    @admin_boost_view("redirect", _("Show missives"))
    def handle_show_missives(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        url += f"?scheduler={obj.pk}"
        return url

    # -- display methods --

    @admin.display(description=_("Progress"))
    def progress_display(self, obj):
        base = f"{obj.total_sent_count} / {obj.total_count} ({obj.progress}%)"
        if obj.total_error_count:
            base += f" — {obj.total_error_count} {_('error(s)')}"
        return base

    @admin.display(description=_("Per channel"))
    def by_type_display(self, obj):
        parts = []
        for missive_type, counts in obj.counts_by_type(only_active=True).items():
            label = MISSIVE_TYPES.get(missive_type, missive_type)
            parts.append(
                f"{label}: {counts['sent']}/{counts['total']} "
                f"({counts['progress']}%) / {counts['error']} err"
            )
        return " | ".join(parts) or "-"

    def task_object_display(self, obj):
        if obj.task_content_type_id and obj.task_object_id:
            task_obj = obj.task_object
            if task_obj:
                return format_html(
                    "<small>{}: {}</small>",
                    obj.task_content_type,
                    task_obj,
                )
            return format_html(
                "<small>{} #{} (deleted)</small>",
                obj.task_content_type,
                obj.task_object_id,
            )
        return "-"

    task_object_display.short_description = _("Task object")


class MissiveScheduledCampaignInline(admin.StackedInline):
    """Inline for missive scheduled campaign model."""

    model = MissiveScheduledCampaign
    extra = 0
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "change_link",
                    "missive_type",
                    "scheduled_send_date",
                ),
            },
        ),
    ) + _SCHEDULED_CAMPAIGN_INLINE_FIELDSETS[1:]
    readonly_fields = [
        "change_link",
        "send_date",
        "ended_at",
    ]

    def change_link(self, obj):
        if not obj.pk:
            return "-"
        url = reverse(
            "admin:django_pymissive_missivescheduledcampaign_change",
            args=[obj.pk],
        )
        return format_html('<a href="{}">{}</a>', url, _("Open scheduled send →"))

    change_link.short_description = ""

    def has_change_permission(self, request, obj=None):
        if not isinstance(obj, MissiveScheduledCampaign):
            return True
        return obj.can_send

    def get_readonly_fields(self, request, obj=None):
        if isinstance(obj, MissiveScheduledCampaign) and not obj.can_send:
            return [f.name for f in MissiveScheduledCampaign._meta.get_fields()
                    if hasattr(f, "column")]
        return list(self.readonly_fields)

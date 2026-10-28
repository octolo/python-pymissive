"""Admin for MissiveScheduledCampaign model."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.forms.formsets import DELETION_FIELD_NAME
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.shortcuts import redirect
from django_boosted import AdminBoostModel  # type: ignore[import-untyped]
from django_boosted.decorators import admin_boost_view, admin_boost_action  # type: ignore[import-untyped]
from pymissive.config import MISSIVE_TYPES

from ..managers.scheduler import MissiveScheduledCampaignQuerySet
from ..models.choices import MissiveStatus, get_missive_style
from ..models.scheduler import (
    SENDING_RUN_DELETE_MESSAGE,
    MissiveScheduledCampaign,
    format_average_send_speed,
)
from .permissions import ActionRightsMixin

if TYPE_CHECKING:
    from django.contrib.admin.options import _FieldsetSpec

#: Animation preset for a missive type. Types absent from this map have no scene.
_ANIMATION_PRESET = {
    "email": "email",
    "email_marketing": "email",
    "ere": "emailAR",
    "sms": "sms",
    "rcs": "sms",
    "voice_call": "voice",
    "notification": "notification",
    "push_notification": "notification",
    "branded": "notification",
    "letter": "postal",
    "hand_delivery": "handDelivery",
    "registered_letter": "registered",
}


def protect_sending_runs(request, runs, protected):
    """Add the runs still being sent to an admin ``protected`` list.

    Django then shows its "cannot delete" page instead of deleting; the
    message tells the user to cancel the send first.
    """
    sending = [run for run in runs if run.is_sending]
    if not sending:
        return protected
    messages.error(request, SENDING_RUN_DELETE_MESSAGE)
    return [
        *protected,
        *(f"{run.campaign} — {formats.localize(timezone.localtime(run.send_date))}" for run in sending),
    ]


class ScheduledCampaignInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            should_delete = form.cleaned_data.get(DELETION_FIELD_NAME, False)
            if self.can_delete and should_delete and form.instance.pk and form.instance.is_sending:
                raise ValidationError(SENDING_RUN_DELETE_MESSAGE)


class CancelRunForm(forms.Form):
    cancel_reason = forms.CharField(
        label=_("Cancel reason"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


_SCHEDULED_CAMPAIGN_INLINE_FIELDSETS: _FieldsetSpec = (
    (
        None,
        {
            "fields": (
                "missive_type",
                "scheduled_send_date",
                "retry_failed",
                "progress_hook",
                "progress_step",
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
                "cancelled_at",
                "cancel_reason",
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
class MissiveScheduledCampaignAdmin(ActionRightsMixin, AdminBoostModel):
    """Admin for missive scheduled campaign model."""

    view_on_site = True

    list_display = [
        "campaign",
        "missive_type",
        "scheduled_send_date",
        "send_date",
        "ended_at",
        "progress_display",
        "average_send_speed_display",
        "by_type_display",
        "by_status_display",
        "task_object_display",
        "comment",
    ]
    list_filter = ["missive_type"]
    readonly_fields = [
        "campaign",
        "send_date",
        "ended_at",
        "cancelled_at",
        "cancel_reason",
        "campaign_snapshot",
        "progress_display",
        "average_send_speed_display",
        "by_type_display",
        "by_status_display",
        "created_at",
        "updated_at",
    ]

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and not obj.can_send:
            for field in (
                "missive_type",
                "scheduled_send_date",
                "progress_hook",
                "progress_step",
                "external_task_backend",
                "task_content_type",
                "task_object_id",
                "task_object_arguments",
                "additional_config",
                "build_target_processors",
            ):
                if field not in readonly:
                    readonly.append(field)
        return readonly

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            return
        # A partial save cannot restore worker-owned fields read before the
        # worker updated them. In particular, updated_at is a heartbeat and
        # must only be touched by the worker.
        if form.changed_data:
            obj.save(update_fields=form.changed_data)

    def get_queryset(self, request):
        queryset = cast(MissiveScheduledCampaignQuerySet, super().get_queryset(request))
        return queryset.with_counts()

    def get_deleted_objects(self, objs, request):
        deleted, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        protected = protect_sending_runs(request, objs, protected)
        return deleted, model_count, perms_needed, protected

    def get_changelist_instance(self, request):
        changelist = super().get_changelist_instance(request)
        MissiveScheduledCampaign.prefetch_pending_targets(changelist.result_list)
        return changelist

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "campaign",
                    "missive_type",
                    "scheduled_send_date",
                    "retry_failed",
                    "progress_hook",
                    "progress_step",
                    "send_date",
                    "ended_at",
                    "cancelled_at",
                    "cancel_reason",
                )
            },
        ),
    ]

    def change_fieldsets(self):
        self.add_to_fieldset(
            _("Progress"),
            [
                "progress_display",
                "average_send_speed_display",
                "by_type_display",
                "by_status_display",
            ],
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
            [
                "build_target_processors",
                "additional_config",
                "campaign_snapshot",
                "comment",
                "created_at",
                "updated_at",
            ],
            classes=("collapse",),
        )

    changeform_actions = {
        "start_campaign": _("Start campaign"),
        "cancel_run": _("Cancel send"),
        "reschedule": _("Reschedule"),
        "duplicate": _("Duplicate"),
    }

    # -- permissions --

    def has_start_campaign_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk and obj.can_send)

    def has_cancel_run_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk and obj.is_running and not obj.cancelled_at)

    def has_reschedule_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk and not obj.can_send)

    def has_duplicate_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk)

    # -- actions --

    @admin_boost_action("start_campaign", _("Start campaign"))
    def handle_start_campaign(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "start_campaign")

    @admin_boost_view("confirm", _("Start campaign"), hidden=True)
    def start_campaign(self, request, obj, confirmed=False):
        self.require_action_rights(request, obj)
        if not obj.can_send:
            messages.error(
                request,
                _("This scheduled campaign cannot be started (already sent or not yet due)."),
            )
            return self.redirect_to_change(obj)
        if not confirmed:
            return {"confirm": _("Are you sure you want to start this scheduled campaign?")}
        obj.start_scheduled_campaign()
        messages.success(request, _("Scheduled campaign started successfully."))
        return redirect(reverse("admin:django_pymissive_missivescheduledcampaign_changelist"))

    @admin_boost_action("cancel_run", _("Cancel send"))
    def handle_cancel_run(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "cancel_run")

    @admin_boost_view("adminform", _("Cancel send"), hidden=True)
    def cancel_run(self, request, obj, form=None):
        self.require_action_rights(request, obj)
        if form is None:
            return {
                "form": CancelRunForm(),
                "save_label": _("Cancel send"),
                "has_change_permission": True,
            }
        if obj.cancel(form.cleaned_data["cancel_reason"]):
            messages.success(
                request,
                _("Cancellation requested: the send stops before its next missive."),
            )
        else:
            messages.error(request, _("Only a send in progress can be cancelled."))
        return self.redirect_to_change(obj)

    @admin_boost_action("reschedule", _("Reschedule"))
    def handle_reschedule(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "reschedule")

    @admin_boost_view("confirm", _("Reschedule"), hidden=True)
    def reschedule(self, request, obj, confirmed=False):
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _("Create a new scheduled send now (duplicating this configuration)?"),
        )
        if waiting:
            return waiting
        new_scheduled = MissiveScheduledCampaign.objects.create(
            campaign=obj.campaign,
            scheduled_send_date=timezone.now(),
            missive_type=obj.missive_type,
            task_content_type=obj.task_content_type,
            task_object_id=obj.task_object_id,
            task_object_arguments=obj.task_object_arguments,
            external_task_backend=obj.external_task_backend,
            progress_hook=obj.progress_hook,
            progress_step=obj.progress_step,
            additional_config=obj.additional_config,
            build_target_processors=obj.build_target_processors,
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
        return self.redirect_to_boost_view(request, object_id, "duplicate")

    @admin_boost_view("confirm", _("Duplicate"), hidden=True)
    def duplicate(self, request, obj, confirmed=False):
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _("Duplicate this scheduled send? The copy will not be started automatically."),
        )
        if waiting:
            return waiting
        new_scheduled = MissiveScheduledCampaign.objects.create(
            campaign=obj.campaign,
            scheduled_send_date=obj.scheduled_send_date,
            missive_type=obj.missive_type,
            task_content_type=obj.task_content_type,
            task_object_id=obj.task_object_id,
            task_object_arguments=obj.task_object_arguments,
            external_task_backend=obj.external_task_backend,
            progress_hook=obj.progress_hook,
            progress_step=obj.progress_step,
            additional_config=obj.additional_config,
            build_target_processors=obj.build_target_processors,
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

    @admin_boost_view(
        "message",
        _("Animations"),
        template_name="django_pymissive/admin/scheduler_animations.html",
        requires_object=False,
    )
    def animations(self, request):
        return {}

    @admin_boost_view("json", _("Progress"))
    def progress(self, request, obj):
        """Live counters of this run, including one block per missive type."""
        return obj.progress_payload()

    @admin_boost_view(
        "message",
        _("Sending"),
        template_name="django_pymissive/admin/scheduler_send_animations.html",
    )
    def send_animations(self, request, obj):
        """One animation per missive type this run still has something to send for."""
        frames = []
        progress = obj.progress_payload()
        for missive_type, counts in progress["by_type"].items():
            total = counts["total"]
            frames.append(
                {
                    "missive_type": missive_type,
                    "preset": _ANIMATION_PRESET.get(missive_type),
                    "label": counts["label"],
                    "total": total,
                    "remaining": max(0, total - counts["sent"] - counts["error"]),
                    "errors": counts["error"],
                }
            )
        return {
            "frames": frames,
            "run_status": progress["status"],
            "progress_url": reverse(
                "admin:django_pymissive_missivescheduledcampaign_progress",
                args=[obj.pk],
            ),
        }

    # -- display methods --

    @admin.display(description=_("Progress"))
    def progress_display(self, obj):
        base = f"{obj.total_sent_count} / {obj.total_count} ({obj.progress}%)"
        if obj.total_error_count:
            base += f" — {obj.total_error_count} {_('error(s)')}"
        # Explains a "By status" column summing above the total: those attempts
        # left the live set when a later run retried them.
        if obj.history_count:
            base += f" — {obj.history_count} {_('retried elsewhere')}"
        speed = format_average_send_speed(obj.average_send_speed)
        if speed:
            base += f" — {speed} {_('per send')}"
        return base

    @admin.display(
        description=_("Average speed per send"),
        ordering="average_send_speed",
    )
    def average_send_speed_display(self, obj):
        return format_average_send_speed(obj.average_send_speed) or "-"

    @admin.display(description=_("Per channel"))
    def by_type_display(self, obj):
        parts = []
        for missive_type, counts in obj.counts_by_type(only_active=True).items():
            label = MISSIVE_TYPES.get(missive_type, missive_type)
            parts.append(f"{label}: {counts['sent']}/{counts['total']} ({counts['progress']}%) / {counts['error']} err")
        return " | ".join(parts) or "-"

    @admin.display(description=_("By status"))
    def by_status_display(self, obj):
        labels = []
        for status, count in obj.counts_by_status(only_active=True).items():
            labels.append(
                self.format_label(
                    f"{count} {MissiveStatus(status).label}",
                    size="small",
                    label_type=get_missive_style(status),
                )
            )
        return format_html_join(" ", "{}", ((label,) for label in labels)) if labels else "-"

    @admin.display(description=_("Task object"))
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


class MissiveScheduledCampaignInline(admin.StackedInline):
    """Inline for missive scheduled campaign model."""

    model = MissiveScheduledCampaign
    formset = ScheduledCampaignInlineFormSet
    extra = 0
    fieldsets: ClassVar[_FieldsetSpec] = cast(
        "_FieldsetSpec",
        (
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
        )
        + tuple(_SCHEDULED_CAMPAIGN_INLINE_FIELDSETS[1:]),
    )
    readonly_fields = [
        "change_link",
        "send_date",
        "ended_at",
        "cancelled_at",
        "cancel_reason",
    ]

    @admin.display(description="")
    def change_link(self, obj):
        if not obj.pk:
            return "-"
        url = reverse(
            "admin:django_pymissive_missivescheduledcampaign_change",
            args=[obj.pk],
        )
        return format_html('<a href="{}">{}</a>', url, _("Open scheduled send →"))

    def has_change_permission(self, request, obj=None):
        # Inlines only see the parent campaign, so per-run rules cannot apply
        # here: existing runs are edited on their own change page.
        return False

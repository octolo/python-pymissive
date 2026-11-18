"""Admin for MissiveCampaign model."""

from typing import cast
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.admin.helpers import AdminForm
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from django.contrib import messages
from django_boosted import AdminBoostModel  # type: ignore[import-untyped]
from django_boosted.decorators import admin_boost_view, admin_boost_action  # type: ignore[import-untyped]

from pymissive.config import MISSIVE_TYPES

from ..models.campaign import MissiveCampaign
from .campaign_step import (
    CAMPAIGN_STEP_INLINE_BY_TYPE,
    BrandedCampaignStepInline,
    CampaignStepAdmin,
    CampaignStepInline,
    campaign_step_fieldsets,
    EmailCampaignStepInline,
    EmailMarketingCampaignStepInline,
    EreCampaignStepInline,
    HandDeliveryCampaignStepInline,
    LetterCampaignStepInline,
    NotificationCampaignStepInline,
    PushNotificationCampaignStepInline,
    RcsCampaignStepInline,
    RegisteredLetterCampaignStepInline,
    SmsCampaignStepInline,
    VoiceCallCampaignStepInline,
)
from ..forms.campaign_step import CampaignStepTypeForm
from ..models.attachment import MissiveBaseAttachment
from ..models.campaign_step import CampaignStep
from ..models.channel_config import admin_missive_type_fields
from ..models.scheduler import MissiveScheduledCampaign, format_average_send_speed
from ..managers.campaign import MissiveCampaignQuerySet
from ..fields import RichTextField
from ..utils import recalculate_attachment_priorities
from .attachment import CampaignAttachmentBaseInline
from .related_object import CampaignRelatedObjectInline
from .scheduler import MissiveScheduledCampaignInline, protect_sending_runs
from .annotations import AnnotationFieldsetMixin, campaign_annotation_names
from .permissions import ActionRightsMixin


@admin.register(MissiveCampaign)
class MissiveCampaignAdmin(
    AnnotationFieldsetMixin,
    ActionRightsMixin,
    AdminBoostModel,
):
    """Admin for missive campaign model."""

    view_on_site = True

    def annotation_names(self) -> tuple[str, ...]:
        return campaign_annotation_names()

    list_display = [
        "subject_display",
        "related_objects_display",
        "types_display",
        "stats_display",
        "targets_display",
        "last_send_date_display",
        "last_ended_at_display",
    ]
    search_fields = [
        "subject",
        "named_id",
        "to_campaignrelatedobject__object_str",
        "to_campaignrelatedobject__object_id",
    ]
    ordering = ["-id"]
    readonly_fields = [
        "named_id",
        "current_scheduler_display",
        "description_snapshot_html",
        "created_at",
        "updated_at",
    ]
    inlines = [
        LetterCampaignStepInline,
        RegisteredLetterCampaignStepInline,
        HandDeliveryCampaignStepInline,
        EreCampaignStepInline,
        EmailCampaignStepInline,
        EmailMarketingCampaignStepInline,
        SmsCampaignStepInline,
        RcsCampaignStepInline,
        VoiceCallCampaignStepInline,
        NotificationCampaignStepInline,
        PushNotificationCampaignStepInline,
        BrandedCampaignStepInline,
        CampaignAttachmentBaseInline,
        CampaignRelatedObjectInline,
        MissiveScheduledCampaignInline,
    ]

    #: Counters the changelist columns below read. Named one by one because
    #: ``with_counts()`` without arguments also annotates the per-status,
    #: per-support, per-type and per-thread breakdowns — many aggregates nothing
    #: here displays, each one a deduplication pass over the same joined rows.
    #: The percentages bring their own recipient counters along.
    changelist_counters = (
        "count_missive",
        "count_recipient",
        "count_event",
        "count_related_object",
        "count_attachment",
        "count_target_pending",
        "count_target_abandoned",
        "pct_recipient_failed",
        "pct_recipient_success",
        "pct_recipient_processing",
        "count_step",
        "send_speed",
        *(f"count_type_{type_key}" for type_key in MISSIVE_TYPES),
    )

    def get_queryset(self, request):
        """Annotate the counters :attr:`changelist_counters` enumerates."""
        queryset = cast(MissiveCampaignQuerySet, super().get_queryset(request))
        return queryset.with_counts(*self.changelist_counters).prefetch_related("to_campaignrelatedobject")

    def get_inline_instances(self, request, obj=None):
        inlines = super().get_inline_instances(request, obj)
        active_types = set(obj.to_campaignstep.values_list("missive_type", flat=True)) if obj is not None else set()
        return [
            inline
            for inline in inlines
            if (not isinstance(inline, CampaignStepInline) or inline.missive_type in active_types)
            and (not isinstance(inline, MissiveScheduledCampaignInline) or bool(active_types))
        ]

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model and issubclass(formset.model, MissiveBaseAttachment):
            self._recalculate_attachment_priorities(formset, form.instance)

    def _recalculate_attachment_priorities(self, formset, parent):
        """Recalculate attachment priorities after inline save (admin bypasses model save logic)."""
        recalculate_attachment_priorities(campaign_id=parent.pk if parent else None)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, RichTextField):
            kwargs.setdefault("required", False)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    changeform_actions = {
        "send_campaign": _("Send Campaign"),
    }
    fieldsets = [
        (
            None,
            {
                "fields": (
                    "named_id",
                    "subject",
                    "description",
                    "description_snapshot_html",
                    "current_scheduler_display",
                ),
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Comment/Timestamps"),
            ["comment", "created_at", "updated_at"],
            classes=("wide", "collapse"),
        )
        self.add_to_fieldset(
            _("Configs"),
            [
                "metadata",
                "additional_context",
                "additional_config",
                "body_processors",
                "first_document_processors",
                "attachment_processors",
                "build_target_processors",
            ],
            classes=("wide", "collapse"),
        )

    @admin_boost_view("redirect", _("Preview"))
    def handle_preview(self, request, obj):
        url = reverse("admin:django_pymissive_campaignstep_changelist")
        return f"{url}?{urlencode({'campaign__id__exact': obj.pk})}"

    def subject_display(self, obj):
        return self.format_with_help_text(obj.subject, format_lazy(_("{} step(s)"), obj.count_step))

    @admin.display(description=_("Related objects"))
    def related_objects_display(self, obj):
        related_objects = list(obj.to_campaignrelatedobject.all())
        if not related_objects:
            return "-"

        labels = format_html_join(
            "",
            '<span class="boost-label small info" style="{}" title="{}">{}</span>',
            (
                (
                    "display:block;max-width:9rem;overflow:hidden;text-overflow:ellipsis;",
                    text,
                    text,
                )
                for related in related_objects[:2]
                for text in [related.object_str or related.object_id]
            ),
        )
        remaining = obj.count_related_object - min(len(related_objects), 2)
        more = format_html("<span>+{}</span>", remaining) if remaining > 0 else ""
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:4px;">'
            '<span style="display:inline-flex;flex-direction:column;gap:2px;min-width:0;">{}</span>'
            "{}"
            "</span>",
            labels,
            more,
        )

    @admin.display(description=_("Types"))
    def types_display(self, obj):
        """Display missive count per type."""
        labels = []
        related_attachment = [
            format_lazy(_("{} related(s)"), obj.count_related_object),
            format_lazy(_("{} attachment(s)"), obj.count_attachment),
        ]
        for type_key, type_label in MISSIVE_TYPES.items():
            count = getattr(obj, f"count_type_{type_key}", 0)
            if count:
                labels.append(self.format_label(f"{count} {type_label}", size="small", label_type="primary"))
        tpl = format_html_join(" ", "{}", ((label,) for label in labels)) if labels else "-"
        return self.format_with_help_text(tpl, " | ".join(str(s) for s in related_attachment))

    @admin.display(description=_("Stats"))
    def stats_display(self, obj):
        """Display recipient status percentages and the event count."""
        rates = [
            self.format_label(
                format_lazy(_("{}% failed"), f"{getattr(obj, 'pct_recipient_failed', 0):.0f}"),
                size="small",
                label_type="danger",
            ),
            self.format_label(
                format_lazy(_("{}% success"), f"{getattr(obj, 'pct_recipient_success', 0):.0f}"),
                size="small",
                label_type="success",
            ),
            self.format_label(
                format_lazy(_("{}% processing"), f"{getattr(obj, 'pct_recipient_processing', 0):.0f}"),
                size="small",
                label_type="warning",
            ),
        ]
        rates_html = format_html_join(" ", "{}", ((rate,) for rate in rates))
        details = [str(format_lazy(_("{} event(s)"), obj.count_event))]
        speed = format_average_send_speed(obj.send_speed)
        if speed:
            details.append(speed)
        return self.format_with_help_text(rates_html, " | ".join(details))

    @admin.display(description=_("Targets"))
    def targets_display(self, obj):
        """Links to the campaign's pending and abandoned selection rows."""
        url = reverse("admin:django_pymissive_campaigntarget_changelist")
        links = [
            format_html(
                '<a href="{}?{}">{}</a>',
                url,
                urlencode({"campaign__id__exact": obj.pk, "state": state}),
                format_lazy(label, count),
            )
            for state, label, count in (
                ("pending", _("{} pending"), obj.count_target_pending),
                ("abandoned", _("{} abandoned"), obj.count_target_abandoned),
            )
        ]
        details = [
            format_lazy(_("{} missive(s)"), obj.count_missive),
            format_lazy(_("{} recipient(s)"), obj.count_recipient),
        ]
        return self.format_with_help_text(
            format_html_join(" | ", "{}", ((link,) for link in links)),
            " | ".join(str(detail) for detail in details),
        )

    @admin.display(description=_("Last send date"))
    def last_send_date_display(self, obj):
        """Display last send date from annotated queryset."""
        return getattr(obj, "last_send_date", None) or "-"

    @admin.display(description=_("Last ended at"))
    def last_ended_at_display(self, obj):
        """Display last ended at from annotated queryset."""
        return getattr(obj, "last_ended_at", None) or "-"

    @admin.display(description=_("Current scheduler"))
    def current_scheduler_display(self, obj):
        """Link to the scheduler that currently reserves this campaign."""
        scheduler_id = obj.current_scheduler_id
        if scheduler_id is None:
            return "-"
        url = reverse("admin:django_pymissive_missivescheduledcampaign_change", args=[scheduler_id])
        return format_html('<a href="{}">{}</a>', url, scheduler_id)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not obj.can_remove:
            return False
        return super().has_delete_permission(request, obj)

    def get_deleted_objects(self, objs, request):
        deleted, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        runs = MissiveScheduledCampaign.objects.filter(campaign_id__in=[obj.pk for obj in objs])
        protected = protect_sending_runs(request, runs.sending(), protected)
        return deleted, model_count, perms_needed, protected

    def has_start_campaign_permission(self, request, obj=None):
        return bool(self.has_action_rights(request, obj) and obj and obj.pk)

    @admin_boost_action("start_campaign", _("Start campaign"))
    def handle_start_campaign(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "start_campaign")

    @admin_boost_view("confirm", _("Start campaign"), hidden=True)
    def start_campaign(self, request, obj, confirmed=False):
        waiting = self.confirm_action(request, obj, confirmed, _("Are you sure you want to start this campaign?"))
        if waiting:
            return waiting
        scheduled = obj.start_campaign()
        messages.success(request, _("Campaign started successfully."))
        return self.redirect_to_change(scheduled)

    @admin_boost_view("redirect", _("Show missives"))
    def handle_show_missives(self, request, obj):
        url = reverse("admin:django_pymissive_missive_changelist")
        url += f"?campaign_step__campaign__id__exact={obj.pk}"
        return url

    @admin_boost_view("adminform", _("Add campaign step"), permission="change")
    def add_campaign_step(self, request, obj, form=None):
        self.require_action_rights(request, obj)
        if not request.user.has_perm(f"{CampaignStep._meta.app_label}.add_{CampaignStep._meta.model_name}"):
            raise PermissionDenied

        missive_type = request.GET.get("missive_type", "")
        inline_class = CAMPAIGN_STEP_INLINE_BY_TYPE.get(missive_type)
        if inline_class is None:
            if form is None:
                return {
                    "form": CampaignStepTypeForm(),
                    "save_label": _("Continue"),
                    "has_change_permission": True,
                }
            url = reverse(
                "admin:django_pymissive_missivecampaign_add_campaign_step",
                args=[obj.pk],
            )
            return redirect(f"{url}?{urlencode({'missive_type': form.cleaned_data['missive_type']})}")

        if form is None:
            position = (obj.to_campaignstep.aggregate(value=Max("position"))["value"] or 0) + 1
            step = inline_class.model(
                campaign=obj,
                missive_type=missive_type,
                position=position,
            )
            step_admin = CampaignStepAdmin(inline_class.model, self.admin_site)
            form_class = step_admin.get_form(
                request,
                step,
                fields=[
                    "position",
                    "label",
                    *admin_missive_type_fields(missive_type),
                    *step_admin.config_fields,
                ],
            )
            step_form = form_class(
                request.POST or None,
                request.FILES or None,
                instance=step,
            )
            return {
                "form": step_form,
                "adminform": AdminForm(
                    step_form,
                    campaign_step_fieldsets(missive_type, include_config=True),
                    {},
                    readonly_fields=step_admin.get_readonly_fields(request, step),
                    model_admin=step_admin,
                ),
                "save_label": _("Add campaign step"),
                "has_change_permission": True,
            }

        step = form.save(commit=False)
        step.campaign = obj
        step.missive_type = missive_type
        step.save()
        form.save_m2m()
        messages.success(request, _("Campaign step added successfully."))
        return self.redirect_to_change(obj)

    @admin_boost_view("redirect", _("Send missive"))
    def handle_send_missive(self, request, obj):
        url = reverse("admin:django_pymissive_missive_add")
        step = obj.to_campaignstep.order_by("position", "pk").first()
        if step is not None:
            url += f"?campaign_step={step.pk}"
        return url

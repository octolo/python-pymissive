"""Admin for MissiveCampaign model."""

from typing import cast
from urllib.parse import urlencode

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from django.contrib import messages
from phonenumber_field.modelfields import PhoneNumberField  # type: ignore[import-untyped]
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField  # type: ignore[import-untyped]
from phonenumber_field.formfields import SplitPhoneNumberField  # type: ignore[import-untyped]
from django_boosted import AdminBoostModel  # type: ignore[import-untyped]
from django_boosted.decorators import admin_boost_view, admin_boost_action  # type: ignore[import-untyped]

from pymissive.config import MISSIVE_TYPES

from ..models.campaign import MissiveCampaign
from ..models.attachment import MissiveBaseAttachment
from ..models.scheduler import MissiveScheduledCampaign
from ..managers.campaign import MissiveCampaignQuerySet
from ..fields import RichTextField
from ..utils import recalculate_attachment_priorities
from .attachment import CampaignAttachmentBaseInline
from .related_object import CampaignRelatedObjectInline
from .scheduler import MissiveScheduledCampaignInline, protect_sending_runs
from .permissions import ActionRightsMixin


@admin.register(MissiveCampaign)
class MissiveCampaignAdmin(ActionRightsMixin, AdminBoostModel):
    """Admin for missive campaign model."""

    view_on_site = True

    list_display = [
        "subject_display",
        "types_display",
        "stats_display",
        "targets_display",
        "last_send_date_display",
        "last_ended_at_display",
    ]
    search_fields = ["subject", "named_id"]
    ordering = ["-id"]
    readonly_fields = [
        "named_id",
        "current_scheduler_display",
        "created_at",
        "updated_at",
    ]
    inlines = [
        MissiveScheduledCampaignInline,
        CampaignAttachmentBaseInline,
        CampaignRelatedObjectInline,
    ]

    #: Counters the changelist columns below read. Named one by one because
    #: ``with_counts()`` without arguments also annotates the per-status,
    #: per-support and per-thread breakdowns — some fifty aggregates nothing
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
        *(f"count_type_{type_key}" for type_key in MISSIVE_TYPES),
    )

    def get_queryset(self, request):
        """Annotate the counters :attr:`changelist_counters` enumerates."""
        queryset = cast(MissiveCampaignQuerySet, super().get_queryset(request))
        return queryset.with_counts(*self.changelist_counters)

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
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            if db_field.null:
                return PhoneNumberFormField(**kwargs)
            return SplitPhoneNumberField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    changeform_actions = {
        "send_campaign": _("Send Campaign"),
    }
    fieldsets = [
        (
            None,
            {
                "fields": ("named_id", "subject", "description", "current_scheduler_display"),
            },
        ),
    ]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            _("Email"),
            [
                "sender_email_name",
                "sender_email",
                "acknowledgement_email",
                "reply_to_email_name",
                "reply_to_email",
                "email_body_text",
                "email_body_rich",
            ],
        )
        self.add_to_fieldset(
            _("SMS / App"),
            [
                "sender_phone_name",
                "sender_phone",
                "phone_body_text",
                "phone_body_rich",
            ],
        )
        self.add_to_fieldset(
            _("Postal"),
            [
                "sender_address_name",
                "sender_address",
                "reply_to_address_name",
                "reply_to_address",
                "acknowledgement_letter",
                "delivery_mode_letter",
                "priority_letter",
                "duplex_printing_letter",
                "color_printing_letter",
                "duplex_printing_registered_letter",
                "color_printing_registered_letter",
                "first_document",
            ],
        )
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

    @admin_boost_view("redirect", _("Preview (email)"))
    def handle_preview_email(self, request, obj):
        base = reverse("django_pymissive:preview", args=["campaign", obj.pk])
        return f"{base}?type=email"

    @admin_boost_view("redirect", _("Preview (SMS)"))
    def handle_preview_sms(self, request, obj):
        base = reverse("django_pymissive:preview", args=["campaign", obj.pk])
        return f"{base}?type=sms"

    @admin_boost_view("redirect", _("Preview (postal)"))
    def handle_preview_postal(self, request, obj):
        base = reverse("django_pymissive:preview", args=["campaign", obj.pk])
        return f"{base}?type=postal"

    def subject_display(self, obj):
        missive_recipients = [
            format_lazy(_("{} missive(s)"), obj.count_missive),
            format_lazy(_("{} recipient(s)"), obj.count_recipient),
        ]
        return self.format_with_help_text(obj.subject, " | ".join(str(s) for s in missive_recipients))

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
        """Display missive/recipient counts and status percentages."""
        related_counts = [
            format_lazy(_("{} missive(s)"), obj.count_missive),
            format_lazy(_("{} event(s)"), obj.count_event),
        ]
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
        return self.format_with_help_text(rates_html, " | ".join(str(s) for s in related_counts))

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
        return format_html_join(" | ", "{}", ((link,) for link in links))

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
        url += f"?campaign={obj.pk}"
        return url

    @admin_boost_view("redirect", _("Send missive"))
    def handle_send_missive(self, request, obj):
        url = reverse("admin:django_pymissive_missive_add")
        url += f"?campaign={obj.pk}"
        return url

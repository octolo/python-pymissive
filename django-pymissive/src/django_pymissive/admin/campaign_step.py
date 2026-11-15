"""Admin for campaign steps."""

from typing import cast
from urllib.parse import urlencode

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField
from phonenumber_field.formfields import SplitPhoneNumberField
from phonenumber_field.modelfields import PhoneNumberField

from ..fields import RichTextField
from ..forms.campaign_step import CampaignStepForm
from ..managers.campaign_step import CampaignStepQuerySet
from ..models.campaign_step import (
    BrandedCampaignStep,
    CampaignStep,
    EmailCampaignStep,
    EmailMarketingCampaignStep,
    EreCampaignStep,
    HandDeliveryCampaignStep,
    LetterCampaignStep,
    NotificationCampaignStep,
    PushNotificationCampaignStep,
    RcsCampaignStep,
    RegisteredLetterCampaignStep,
    SmsCampaignStep,
    VoiceCallCampaignStep,
)
from ..models.channel_config import ADMIN_MISSIVE_TYPE_FIELDS
from ..models.choices import get_missive_support_from_type
from ..models.scheduler import format_average_send_speed


_COMPACT_FIELD_PAIRS = {
    ("position", "label"),
    ("sender_name", "sender_email"),
    ("sender_name", "sender_phone"),
    ("sender_name", "sender_address"),
    ("reply_to_name", "reply_to_email"),
    ("reply_to_name", "reply_to_address"),
    ("duplex_printing", "color_printing"),
    ("brand_name", "subject"),
}


def compact_field_rows(fields):
    """Group adjacent related fields on the same native admin row."""
    rows = []
    index = 0
    while index < len(fields):
        pair = tuple(fields[index : index + 2])
        if pair in _COMPACT_FIELD_PAIRS:
            rows.append(pair)
            index += 2
        else:
            rows.append(fields[index])
            index += 1
    return rows


def campaign_step_fieldsets(missive_type, *, include_campaign=False, include_config=False):
    common: list[str | tuple[str, str]] = [("position", "label")]
    if include_campaign:
        common.insert(0, "campaign")
        common.append("missive_type")
    fieldsets = [
        (None, {"fields": common}),
        (_("Content"), {"fields": compact_field_rows(list(ADMIN_MISSIVE_TYPE_FIELDS[missive_type]))}),
    ]
    if include_config:
        fieldsets.append(
            (
                _("Configuration"),
                {
                    "fields": CampaignStepAdmin.config_fields,
                    "classes": ("collapse",),
                },
            )
        )
    return fieldsets


class CampaignStepInline(admin.StackedInline):
    """One channel's steps, with that channel's fields, on the campaign page."""

    extra = 0
    form = CampaignStepForm
    ordering = ["position", "pk"]
    readonly_fields = ["body_rich_snapshot_html"]
    show_change_link = True
    missive_type = ""

    @property
    def step_support(self):
        return get_missive_support_from_type(self.missive_type)

    def get_fieldsets(self, request, obj=None):
        return campaign_step_fieldsets(self.missive_type)

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(missive_type=self.missive_type)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if self.step_support == "address":
            if db_field.name == "body_rich":
                kwargs.setdefault("label", _("First document"))
                kwargs.setdefault("help_text", _("Letter body. It is not one of the shared attachments."))
            elif db_field.name == "body_rich_snapshot_html":
                kwargs.setdefault("label", _("First document HTML snapshot"))
        if isinstance(db_field, RichTextField):
            kwargs.setdefault("required", False)
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            if db_field.null:
                return PhoneNumberFormField(**kwargs)
            return SplitPhoneNumberField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class EmailCampaignStepInline(CampaignStepInline):
    model = EmailCampaignStep
    missive_type = EmailCampaignStep.campaign_step_type


class EmailMarketingCampaignStepInline(CampaignStepInline):
    model = EmailMarketingCampaignStep
    missive_type = EmailMarketingCampaignStep.campaign_step_type


class EreCampaignStepInline(CampaignStepInline):
    model = EreCampaignStep
    missive_type = EreCampaignStep.campaign_step_type


class SmsCampaignStepInline(CampaignStepInline):
    model = SmsCampaignStep
    missive_type = SmsCampaignStep.campaign_step_type


class RcsCampaignStepInline(CampaignStepInline):
    model = RcsCampaignStep
    missive_type = RcsCampaignStep.campaign_step_type


class VoiceCallCampaignStepInline(CampaignStepInline):
    model = VoiceCallCampaignStep
    missive_type = VoiceCallCampaignStep.campaign_step_type


class LetterCampaignStepInline(CampaignStepInline):
    model = LetterCampaignStep
    missive_type = LetterCampaignStep.campaign_step_type


class RegisteredLetterCampaignStepInline(CampaignStepInline):
    model = RegisteredLetterCampaignStep
    missive_type = RegisteredLetterCampaignStep.campaign_step_type


class HandDeliveryCampaignStepInline(CampaignStepInline):
    model = HandDeliveryCampaignStep
    missive_type = HandDeliveryCampaignStep.campaign_step_type


class NotificationCampaignStepInline(CampaignStepInline):
    model = NotificationCampaignStep
    missive_type = NotificationCampaignStep.campaign_step_type


class PushNotificationCampaignStepInline(CampaignStepInline):
    model = PushNotificationCampaignStep
    missive_type = PushNotificationCampaignStep.campaign_step_type


class BrandedCampaignStepInline(CampaignStepInline):
    model = BrandedCampaignStep
    missive_type = BrandedCampaignStep.campaign_step_type


CAMPAIGN_STEP_INLINE_BY_TYPE = {
    inline.model.campaign_step_type: inline
    for inline in (
        EmailCampaignStepInline,
        EmailMarketingCampaignStepInline,
        EreCampaignStepInline,
        SmsCampaignStepInline,
        RcsCampaignStepInline,
        VoiceCallCampaignStepInline,
        LetterCampaignStepInline,
        RegisteredLetterCampaignStepInline,
        HandDeliveryCampaignStepInline,
        NotificationCampaignStepInline,
        PushNotificationCampaignStepInline,
        BrandedCampaignStepInline,
    )
}


@admin.register(CampaignStep)
class CampaignStepAdmin(AdminBoostModel):
    """One physical model, with only the fields of its current channel shown."""

    form = CampaignStepForm
    list_display = [
        "position_type_display",
        "label_display",
        "stats_display",
        "targets_display",
        "last_send_date_display",
        "last_ended_at_display",
        "preview_display",
    ]
    list_select_related = ("campaign",)
    list_filter = ["campaign", "missive_type"]
    search_fields = ["label", "campaign__subject"]
    ordering = ["campaign", "position"]
    raw_id_fields = ["campaign"]
    readonly_fields = ["body_rich_snapshot_html"]

    common_fields = ["campaign", "position", "label", "missive_type"]
    config_fields = [
        "metadata",
        "additional_context",
        "additional_config",
        "body_processors",
        "first_document_processors",
        "attachment_processors",
        "build_target_processors",
    ]
    changelist_counters = (
        "count_missive",
        "count_recipient",
        "count_event",
        "count_target_pending",
        "count_target_abandoned",
        "pct_recipient_failed",
        "pct_recipient_success",
        "pct_recipient_processing",
        "send_speed",
    )

    def get_queryset(self, request):
        queryset = cast(CampaignStepQuerySet, super().get_queryset(request))
        return queryset.with_counts(*self.changelist_counters).with_last_run_dates()

    def get_fieldsets(self, request, obj=None):
        if obj is None or not obj.missive_type:
            return [
                (None, {"fields": self.common_fields}),
                (_("Configuration"), {"fields": self.config_fields, "classes": ("collapse",)}),
            ]
        return campaign_step_fieldsets(
            obj.missive_type,
            include_campaign=True,
            include_config=True,
        )

    def get_form(self, request, obj=None, change=False, **kwargs):
        self._editing_step = obj
        try:
            return super().get_form(request, obj, change=change, **kwargs)
        finally:
            self._editing_step = None

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        step = getattr(self, "_editing_step", None)
        if step is not None and step.support == "address":
            if db_field.name == "body_rich":
                kwargs.setdefault("label", _("First document"))
                kwargs.setdefault("help_text", _("Letter body. It is not one of the shared attachments."))
            elif db_field.name == "body_rich_snapshot_html":
                kwargs.setdefault("label", _("First document HTML snapshot"))
        if isinstance(db_field, RichTextField):
            kwargs.setdefault("required", False)
        if isinstance(db_field, PhoneNumberField):
            kwargs.setdefault("required", False)
            if db_field.null:
                return PhoneNumberFormField(**kwargs)
            return SplitPhoneNumberField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description=_("Position"), ordering="position")
    def position_type_display(self, obj):
        return self.format_with_help_text(
            f"{obj.position}. {obj.get_missive_type_display()}",
            obj.campaign.subject,
        )

    @admin.display(description=_("Label"), ordering="label")
    def label_display(self, obj):
        return obj.label or "-"

    @admin.display(description=_("Stats"))
    def stats_display(self, obj):
        rates = [
            self.format_label(
                format_lazy(_("{}% failed"), f"{obj.pct_recipient_failed:.0f}"),
                size="small",
                label_type="danger",
            ),
            self.format_label(
                format_lazy(_("{}% success"), f"{obj.pct_recipient_success:.0f}"),
                size="small",
                label_type="success",
            ),
            self.format_label(
                format_lazy(_("{}% processing"), f"{obj.pct_recipient_processing:.0f}"),
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
        url = reverse("admin:django_pymissive_campaigntarget_changelist")
        links = [
            format_html(
                '<a href="{}?{}">{}</a>',
                url,
                urlencode({"campaign_step__id__exact": obj.pk, "state": state}),
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

    @admin.display(description=_("Last send date"), ordering="last_send_date")
    def last_send_date_display(self, obj):
        return obj.last_send_date or "-"

    @admin.display(description=_("Last ended at"), ordering="last_ended_at")
    def last_ended_at_display(self, obj):
        return obj.last_ended_at or "-"

    @admin.display(description=_("Preview"))
    def preview_display(self, obj):
        url = reverse("django_pymissive:preview_campaign_step", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Preview"))

    @admin_boost_view("redirect", _("Preview"))
    def handle_preview(self, request, obj):
        return obj.get_browser_preview_path()

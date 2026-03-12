"""Admin for MissiveCampaign model."""

from urllib.parse import unquote

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from phonenumber_field.modelfields import PhoneNumberField
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField
from phonenumber_field.formfields import SplitPhoneNumberField
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view

from pymissive.config import MISSIVE_TYPES

from ..models.campaign import MissiveCampaign, MissiveScheduledCampaign
from ..models.attachment import MissiveBaseAttachment
from ..utils import recalculate_attachment_priorities
from .attachment import CampaignAttachmentInline, CampaignVirtualAttachmentInline
from .related_object import CampaignRelatedObjectInline 


@admin.register(MissiveScheduledCampaign)
class MissiveScheduledCampaignAdmin(AdminBoostModel):
    """Admin for missive scheduled campaign model."""

    list_display = [
        "campaign",
        "scheduled_send_date",
        "send_date",
        "ended_at",
        "comment",
        "additional_config",
    ]
    readonly_fields = [
        "campaign",
        "scheduled_send_date",
        "send_date",
        "ended_at",
        "created_at",
        "updated_at",
    ]


class MissiveScheduledCampaignInline(admin.TabularInline):
    """Inline for missive scheduled campaign model."""

    model = MissiveScheduledCampaign
    extra = 0
    fields = [
        "scheduled_send_date",
        "additional_config",
        "send_date",
        "ended_at",
    ]
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
        "subject_display",
        "types_display",
        "stats_display",
        "last_send_date_display",
        "last_ended_at_display",
    ]
    search_fields = ["subject"]
    ordering = ["-id"]
    readonly_fields = [
        "buttons_show_and_preview_email",
        "buttons_show_and_preview_sms",
        "buttons_show_and_preview_postal",
        "created_at",
        "updated_at",
    ]
    inlines = [
        MissiveScheduledCampaignInline,
        CampaignAttachmentInline,
        CampaignVirtualAttachmentInline,
        CampaignRelatedObjectInline,
    ]

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model and issubclass(formset.model, MissiveBaseAttachment):
            self._recalculate_attachment_priorities(formset, form.instance)

    def _recalculate_attachment_priorities(self, formset, parent):
        """Recalculate attachment priorities after inline save (admin bypasses model save logic)."""
        recalculate_attachment_priorities(campaign_id=parent.pk if parent else None)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
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
                "fields": (
                    "subject",
                    "description",
                )
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
                "body_text",
                "body_html",
                "buttons_show_and_preview_email",
            ],
        )
        self.add_to_fieldset(
            _("SMS"),
            [
                "sender_phone_name",
                "sender_phone",
                "body_sms",
                "buttons_show_and_preview_sms",
            ],
        )
        self.add_to_fieldset(
            _("Postal"),
            [
                "sender_address_name",
                "sender_address",
                "reply_to_address_name",
                "reply_to_address",
                "acknowledgement_postal",
                "delivery_mode_postal",
                "priority_postal",
                "body_postal",
                "buttons_show_and_preview_postal",
            ],
        )
        self.add_to_fieldset(
            _("Comment/Timestamps"),
            ["comment", "created_at", "updated_at"],
            classes=("wide", "collapse"),
        )
        self.add_to_fieldset(
            _("Configs"),
            ["metadata", "additional_context", "additional_config"],
            classes=("wide", "collapse"),
        )

    def _preview_buttons(self, obj, preview_type):
        """Show and Preview buttons for a given type (email, sms, postal)."""
        preview_url = reverse("django_pymissive:preview_form", args=["campaign"])
        buttons_html = []
        if obj.pk:
            base_url = reverse("django_pymissive:preview", args=["campaign", obj.pk])
            buttons_html.append(
                format_html(
                    '<a class="button" href="{}?type={}" target="_blank">{}</a>',
                    base_url,
                    preview_type,
                    _("Show"),
                )
            )
        pk_param = f"&pk={obj.pk}" if obj.pk else ""
        buttons_html.append(
            format_html(
                '<button type="submit" form="missivecampaign_form" formaction="{}?type={}{}" formmethod="post" formtarget="_blank" class="button" name="_preview" value="{}" style="margin-left: 10px;">{}</button>',
                preview_url,
                preview_type,
                pk_param,
                preview_type,
                _("Preview"),
            )
        )
        return mark_safe(" ".join(str(btn) for btn in buttons_html))  # nosec B703 B308

    def buttons_show_and_preview_email(self, obj):
        return self._preview_buttons(obj, "email")

    buttons_show_and_preview_email.short_description = _("Email: Show and Preview")

    def buttons_show_and_preview_sms(self, obj):
        return self._preview_buttons(obj, "sms")

    buttons_show_and_preview_sms.short_description = _("SMS: Show and Preview")

    def buttons_show_and_preview_postal(self, obj):
        return self._preview_buttons(obj, "postal")

    buttons_show_and_preview_postal.short_description = _("Postal: Show and Preview")

    def subject_display(self, obj):
        missive_recipients = [
            format_lazy(_("{} missive(s)"), obj.count_missive),
            format_lazy(_("{} recipient(s)"), obj.count_recipient),
        ]
        return self.format_with_help_text(obj.subject, " | ".join(str(s) for s in missive_recipients))

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
                labels.append(
                    self.format_label(f"{count} {type_label}", size="small", label_type="primary")
                )
        tpl = mark_safe(" ".join(str(l) for l in labels)) if labels else "-"
        return self.format_with_help_text(tpl, " | ".join(str(s) for s in related_attachment))


    types_display.short_description = _("Types")

    def stats_display(self, obj):
        """Display missive/recipient counts and status percentages."""
        related_counts = [
            format_lazy(_("{} missive(s)"), obj.count_missive),
            format_lazy(_("{} event(s)"), obj.count_event),
        ]
        rates = [
            self.format_label(
                format_lazy(_("{}% failed"), f"{obj.pct_failed:.0f}"),
                size="small",
                label_type="danger",
            ),
            self.format_label(
                format_lazy(_("{}% success"), f"{obj.pct_success:.0f}"),
                size="small",
                label_type="success",
            ),
            self.format_label(
                format_lazy(_("{}% processing"), f"{obj.pct_processing:.0f}"),
                size="small",
                label_type="warning",
            ),
        ]
        return self.format_with_help_text(mark_safe(" ".join(rates)), " | ".join(str(s) for s in related_counts))

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
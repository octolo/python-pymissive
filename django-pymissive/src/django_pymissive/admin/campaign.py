"""Admin for MissiveCampaign model."""

from urllib.parse import unquote

from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy
from django.contrib import messages
from django.shortcuts import redirect
from phonenumber_field.modelfields import PhoneNumberField
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField
from phonenumber_field.formfields import SplitPhoneNumberField
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view, admin_boost_action

from pymissive.config import MISSIVE_TYPES

from ..models.campaign import MissiveCampaign, MissiveScheduledCampaign
from ..models.attachment import MissiveBaseAttachment
from ..fields import RichTextField
from ..utils import recalculate_attachment_priorities
from .attachment import CampaignAttachmentBaseInline
from .related_object import CampaignRelatedObjectInline


_SCHEDULED_CAMPAIGN_INLINE_FIELDSETS = (
    (
        None,
        {
            "fields": (
                "missive_type",
                "scheduled_send_date",
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

    list_display = [
        "campaign",
        "missive_type",
        "scheduled_send_date",
        "send_date",
        "ended_at",
        "task_object_display",
        "comment",
    ]
    list_filter = ["missive_type"]
    readonly_fields = [
        "campaign",
        "send_date",
        "ended_at",
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

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "campaign",
                    "missive_type",
                    "scheduled_send_date",
                    "send_date",
                    "ended_at",
                )
            },
        ),
    ]

    def change_fieldsets(self):
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

    def has_start_campaign_permission(self, request, obj=None):
        return bool(obj and obj.pk and obj.can_send)

    def has_reschedule_permission(self, request, obj=None):
        return bool(obj and obj.pk and not obj.can_send)

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
            messages.error(request, _("This scheduled campaign cannot be started (already sent or not yet due)."))
            return redirect(
                reverse("admin:django_pymissive_missivescheduledcampaign_change", args=[obj.pk])
            )
        if not confirmed:
            return {"confirm": _("Are you sure you want to start this scheduled campaign?")}
        obj.start_scheduled_campaign()
        messages.success(request, _("Scheduled campaign started successfully."))
        return redirect(reverse("admin:django_pymissive_missivescheduledcampaign_changelist"))

    def has_duplicate_permission(self, request, obj=None):
        return bool(obj and obj.pk)

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
        # When called from get_formsets_with_inlines, obj is the *parent*
        # MissiveCampaign — not a MissiveScheduledCampaign instance.
        # Allow the inline to render; per-row locking is handled via
        # get_readonly_fields below.
        if not isinstance(obj, MissiveScheduledCampaign):
            return True
        return obj.can_send

    def get_readonly_fields(self, request, obj=None):
        if isinstance(obj, MissiveScheduledCampaign) and not obj.can_send:
            return [f.name for f in MissiveScheduledCampaign._meta.get_fields()
                    if hasattr(f, "column")]
        return list(self.readonly_fields)


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
        "created_at",
        "updated_at",
    ]
    inlines = [
        MissiveScheduledCampaignInline,
        CampaignAttachmentBaseInline,
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
                "fields": ("subject", "description"),
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
            ],
        )
        self.add_to_fieldset(
            _("SMS"),
            [
                "sender_phone_name",
                "sender_phone",
                "body_sms",
            ],
        )
        self.add_to_fieldset(
            _("Postal"),
            [
                "sender_address_name",
                "sender_address",
                "reply_to_address_name",
                "reply_to_address",
                "acknowledgement_lre",
                "delivery_mode_lre",
                "priority_lre",
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
        tpl = mark_safe(" ".join(str(label) for label in labels)) if labels else "-"
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

    def has_start_campaign_permission(self, request, obj=None):
        return obj and obj.pk

    @admin_boost_action("start_campaign", _("Start campaign"))
    def handle_start_campaign(self, request, object_id):
        object_id = unquote(object_id)
        obj = self.get_object(request, object_id)
        return redirect(reverse("admin:django_pymissive_missivecampaign_start_campaign", args=[obj.pk]))

    @admin_boost_view("confirm", _("Start campaign"), hidden=True)
    def start_campaign(self, request, obj, confirmed=False):
        if not confirmed:
            return {"confirm": _("Are you sure you want to start this campaign?")}
        obj.start_campaign()
        messages.success(request, _("Campaign started successfully."))
        return redirect(reverse("admin:django_pymissive_missivecampaign_changelist"))

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

"""Admin for CampaignTarget."""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django_boosted import AdminBoostModel  # type: ignore[import-untyped]
from django_boosted.decorators import admin_boost_action, admin_boost_view  # type: ignore[import-untyped]

from ..models.campaign_target import CampaignRecipientTarget, CampaignTarget
from .permissions import ActionRightsMixin
from .related_object import BaseRelatedObjectAdmin


def _change_link(obj, label):
    opts = obj._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, label)


def _recipient_text(value):
    if not isinstance(value, dict):
        return value
    name = value.get("name") or ""
    contact = next(
        (value[key] for key in ("email", "phone", "notification_id", "address") if value.get(key)),
        "",
    )
    if name and contact:
        return f"{name} — {contact}"
    return name or contact or str(value)


TARGET_STATES = {
    "pending": (_("Pending"), CampaignTarget.active_q()),
    "with_missive": (_("With missive"), Q(missive__isnull=False)),
    "abandoned": (_("Abandoned"), Q(abandoned_at__isnull=False)),
}


class TargetStateFilter(admin.SimpleListFilter):
    title = _("State")
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [(key, label) for key, (label, _condition) in TARGET_STATES.items()]

    def queryset(self, request, queryset):
        state = TARGET_STATES.get(self.value() or "")
        return queryset.filter(state[1]) if state else queryset


class AbandonTargetForm(forms.Form):
    abandon_reason = forms.CharField(
        label=_("Abandon reason"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class CampaignRecipientTargetInline(admin.TabularInline):
    """Optional contact lists, one row per recipient type."""

    model = CampaignRecipientTarget
    extra = 0
    fields = ["recipient_type", "values"]


@admin.register(CampaignTarget)
class CampaignTargetAdmin(ActionRightsMixin, AdminBoostModel, BaseRelatedObjectAdmin):
    """Admin for a campaign selection row."""

    inlines = [CampaignRecipientTargetInline]

    list_display = [
        "object_str",
        "campaign",
        "missive_type",
        "object_url_link_display",
        "state_display",
        "missive",
        "created_at",
    ]
    list_display_links = ["object_str"]
    list_filter = [
        TargetStateFilter,
        "missive_type",
        "created_at",
    ]
    list_select_related = ("campaign", "content_type", "missive")
    search_fields = [
        "object_str",
        "object_id",
        "campaign__subject",
    ]
    readonly_fields = [
        "object_str",
        "object_url_link_display",
        "targets_display",
        "abandoned_at",
        "abandon_reason",
        "history_display",
        "thread_missives_display",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["campaign", "missive"]
    actions = ["abandon_selected"]

    def change_fieldsets(self):
        """Configure fieldsets for the change view."""
        self.add_to_fieldset(
            None,
            [
                "campaign",
                "missive_type",
                "content_type",
                "object_id",
                "object_url_link_display",
                "targets_display",
                "missive",
                "build_target_processors",
                "abandoned_at",
                "abandon_reason",
            ],
        )
        self.add_to_fieldset(
            _("History"),
            ["history_display", "thread_missives_display"],
        )
        self.add_to_fieldset(
            _("Timestamps"),
            ["created_at", "updated_at"],
        )

    @admin.display(description=_("Recipients"))
    def targets_display(self, obj):
        if not obj or not obj.pk:
            return "-"
        values = obj.targets
        if not values:
            return "-"
        return format_html(
            "<ul>{}</ul>",
            format_html_join("", "<li>{}</li>", ((_recipient_text(value),) for value in values)),
        )

    @admin.display(description=_("State"))
    def state_display(self, obj):
        if obj.abandoned_at:
            return self.format_label(
                TARGET_STATES["abandoned"][0],
                size="small",
                label_type="danger",
            )
        if obj.missive_id:
            return self.format_label(
                TARGET_STATES["with_missive"][0],
                size="small",
                label_type="success",
            )
        return self.format_label(TARGET_STATES["pending"][0], size="small", label_type="warning")

    @admin.display(description=_("Selections of this target"))
    def history_display(self, obj):
        if not obj or not obj.pk:
            return "-"
        rows = [
            (
                _change_link(row, formats.localize(timezone.localtime(row.created_at))),
                _change_link(row.missive, row.missive.get_status_display()) if row.missive_id else "",
                _("Abandoned: %(reason)s") % {"reason": row.abandon_reason or "-"} if row.abandoned_at else "",
            )
            for row in obj.history()
        ]
        return format_html(
            "<ul>{}</ul>",
            format_html_join("", "<li>{} {} {}</li>", rows),
        )

    @admin.display(description=_("Missives of the thread"))
    def thread_missives_display(self, obj):
        if not obj or not obj.pk:
            return "-"
        missives = [
            (
                _change_link(missive, formats.localize(timezone.localtime(missive.created_at))),
                missive.get_status_display(),
                missive.get_thread_type_display(),
            )
            for missive in obj.thread_missives()
        ]
        if not missives:
            return "-"
        return format_html(
            "<ul>{}</ul>",
            format_html_join("", "<li>{} — {} ({})</li>", missives),
        )

    @admin_boost_view("redirect", _("Preview"))
    def preview(self, request, obj):
        return obj.get_browser_preview_path()

    def has_generate_missive_permission(self, request, obj=None):
        """The button only exists while this row is still a checkbox."""
        return bool(self.has_action_rights(request, obj) and obj and obj.pk and obj.is_active())

    def has_abandon_permission(self, request, obj=None):
        return self.has_generate_missive_permission(request, obj)

    @admin_boost_action("generate_missive", _("Generate missive"))
    def handle_generate_missive(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "generate_missive")

    @admin_boost_view("confirm", _("Generate missive"), hidden=True)
    def generate_missive(self, request, obj, confirmed=False):
        self.require_action_rights(request, obj)
        if obj.missive_id:
            return self.redirect_to_change(obj.missive)
        waiting = self.confirm_action(
            request,
            obj,
            confirmed,
            _("Generate a draft missive for this target?"),
        )
        if waiting:
            return waiting

        from ..services import generate_target

        try:
            missive = generate_target(obj)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return self.redirect_to_change(obj)
        except (ValueError, ImportError) as exc:
            messages.error(request, str(exc))
            return self.redirect_to_change(obj)
        if missive is None:
            messages.error(
                request,
                _("No missive could be generated for this target."),
            )
            return self.redirect_to_change(obj)
        messages.success(request, _("Missive generated."))
        return self.redirect_to_change(missive)

    @admin_boost_action("abandon", _("Abandon"))
    def handle_abandon(self, request, object_id):
        return self.redirect_to_boost_view(request, object_id, "abandon")

    @admin_boost_view("adminform", _("Abandon"), hidden=True)
    def abandon(self, request, obj, form=None):
        self.require_action_rights(request, obj)
        if form is None:
            return {
                "form": AbandonTargetForm(),
                "save_label": _("Abandon"),
                "has_change_permission": True,
            }
        if obj.abandon(form.cleaned_data["abandon_reason"]):
            messages.success(request, _("Target abandoned."))
        else:
            messages.error(request, _("Only a target still waiting for its missive can be abandoned."))
        return self.redirect_to_change(obj)

    @admin.action(description=_("Abandon selected targets"))
    def abandon_selected(self, request, queryset):
        self.require_action_rights(request)
        now = timezone.now()
        abandoned = queryset.filter(CampaignTarget.active_q()).update(
            abandoned_at=now,
            updated_at=now,
        )
        self.message_user(
            request,
            ngettext(
                "%(count)d target abandoned.",
                "%(count)d targets abandoned.",
                abandoned,
            )
            % {"count": abandoned},
        )

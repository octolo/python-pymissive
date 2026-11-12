"""Admin for campaign steps and their channel-specific proxies."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django_boosted.decorators import admin_boost_view
from phonenumber_field.formfields import PhoneNumberField as PhoneNumberFormField
from phonenumber_field.formfields import SplitPhoneNumberField
from phonenumber_field.modelfields import PhoneNumberField
from pymissive.config import missive_types_for_support

from ..fields import RichTextField
from ..models.campaign_step import (
    BrandedCampaignStep,
    CampaignStep,
    EmailCampaignStep,
    PhoneCampaignStep,
    PostalCampaignStep,
)

class CampaignStepInline(admin.TabularInline):
    """Ordered steps on the campaign change page."""

    model = CampaignStep
    extra = 0
    fields = ["position", "label", "missive_type"]
    ordering = ["position", "pk"]
    show_change_link = True


@admin.register(CampaignStep)
class CampaignStepAdmin(AdminBoostModel):
    """One physical model, with only the fields of its current channel shown."""

    list_display = ["position", "label", "missive_type", "campaign"]
    list_filter = ["missive_type"]
    search_fields = ["label", "campaign__subject"]
    ordering = ["campaign", "position"]
    raw_id_fields = ["campaign"]
    step_support = ""

    common_fields = ["campaign", "position", "label", "missive_type"]
    channel_fields = {
        "email": [
            "subject",
            "sender_name",
            "sender_email",
            "reply_to_name",
            "reply_to_email",
            "acknowledgement",
            "body_text",
            "body_rich",
            "body_rich_snapshot_html",
        ],
        "phone": [
            "subject",
            "sender_name",
            "sender_phone",
            "body_text",
        ],
        "address": [
            "subject",
            "sender_name",
            "sender_address",
            "reply_to_name",
            "reply_to_address",
            "acknowledgement",
            "delivery_mode",
            "priority",
            "duplex_printing",
            "color_printing",
            "body_rich",
            "body_rich_snapshot_html",
        ],
        "application": [
            "brand_name",
            "subject",
            "sender_name",
            "body_text",
            "body_rich",
            "body_rich_snapshot_html",
        ],
    }
    config_fields = [
        "metadata",
        "additional_context",
        "additional_config",
        "body_processors",
        "first_document_processors",
        "attachment_processors",
        "build_target_processors",
    ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.step_support:
            queryset = queryset.filter(missive_type__in=missive_types_for_support(self.step_support))
        return queryset

    def get_fieldsets(self, request, obj=None):
        support = self.step_support or (obj.support if obj is not None else "")
        fieldsets = [(None, {"fields": self.common_fields})]
        fields = self.channel_fields.get(support)
        if fields:
            fieldsets.append((_("Content"), {"fields": fields}))
        fieldsets.append((_("Configuration"), {"fields": self.config_fields, "classes": ("collapse",)}))
        return fieldsets

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

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "missive_type" and self.step_support:
            allowed = set(missive_types_for_support(self.step_support))
            kwargs["choices"] = [choice for choice in db_field.choices if choice[0] in allowed]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    @admin_boost_view("redirect", _("Preview"))
    def handle_preview(self, request, obj):
        return obj.get_browser_preview_path()


@admin.register(EmailCampaignStep)
class EmailCampaignStepAdmin(CampaignStepAdmin):
    step_support = "email"


@admin.register(PhoneCampaignStep)
class PhoneCampaignStepAdmin(CampaignStepAdmin):
    step_support = "phone"


@admin.register(PostalCampaignStep)
class PostalCampaignStepAdmin(CampaignStepAdmin):
    step_support = "address"


@admin.register(BrandedCampaignStep)
class BrandedCampaignStepAdmin(CampaignStepAdmin):
    step_support = "application"

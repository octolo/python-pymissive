"""Admin for MissiveRelatedObject model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel
from django.utils.safestring import mark_safe
from django.urls import reverse

from ..models.related_object import MissiveRelatedObject, CampaignRelatedObject


class BaseRelatedObjectAdmin:
    """Base admin for related objects."""

    def object_url_change(self, obj):
        """Return the url for the related object."""
        try:
            return reverse(
                f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change",
                args=[obj.object_id],
            )
        except Exception as e:
            return None
    
    @admin.display(description=_("Object URL Link"))
    def object_url_link_display(self, obj):
        """Return a link to the related object in the admin site."""
        if not obj or not obj.content_type_id or not obj.object_id:
            return "-"
        label = obj.object_str or f"{obj.content_type} #{obj.object_id}"
        url = self.object_url_change(obj)
        if not url:
            return label
        return mark_safe(f'<a href="{url}">{label}</a>')


class MissiveRelatedObjectInline(admin.TabularInline, BaseRelatedObjectAdmin):
    """Inline for missive related objects."""

    model = MissiveRelatedObject
    extra = 0
    fields = [
        "content_type",
        "object_id",
        "object_url_link_display",
    ]
    readonly_fields = ["object_url_link_display",]


@admin.register(MissiveRelatedObject)
class MissiveRelatedObjectAdmin(AdminBoostModel, BaseRelatedObjectAdmin):
    """Admin for missive related object model."""

    list_display = [
        "missive",
        "content_type",
        "object_url_link_display",
        "created_at",
    ]
    list_filter = [
        "content_type",
        "created_at",
    ]
    search_fields = [
        "missive__subject",
        "missive__recipients__name",
        "missive__recipients__email",
        "missive__recipients__phone",
        "missive__recipients__address",
    ]
    readonly_fields = [
        "object_url_link_display",
        "created_at",
    ]
    raw_id_fields = ["missive",]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            None,
            ["missive", "content_type", "object_id", "object_url_link_display", "comment"],
        )
        self.add_to_fieldset(
            _("Timestamps"),
            ["created_at"],
        )


class CampaignRelatedObjectInline(admin.TabularInline, BaseRelatedObjectAdmin):
    """Inline for campaign related objects."""

    model = CampaignRelatedObject
    extra = 0
    fields = [
        "content_type",
        "object_id",
        "object_url_link_display",
    ]
    readonly_fields = ["object_url_link_display",]



@admin.register(CampaignRelatedObject)
class CampaignRelatedObjectAdmin(AdminBoostModel, BaseRelatedObjectAdmin):
    """Admin for campaign related object model."""

    list_display = [
        "campaign",
        "content_type",
        "object_url_link_display",
        "created_at",
    ]
    list_filter = [
        "content_type",
        "created_at",
    ]
    search_fields = [
        "campaign__name",
    ]
    readonly_fields = [
        "object_url_link_display",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["campaign",]

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            None,
            ["campaign", "content_type", "object_id", "object_url_link_display"],
        )
        self.add_to_fieldset(
            _("Comment/Timestamps"),
            ["comment", "created_at", "updated_at"],
        )
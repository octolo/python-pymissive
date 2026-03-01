"""Admin for MissiveRelatedObject model."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..models.related_object import MissiveRelatedObject


class MissiveRelatedObjectInline(admin.TabularInline):
    """Inline for missive related objects."""

    model = MissiveRelatedObject
    extra = 0
    fields = [
        "content_type",
        "object_id",
        "object_str",
    ]
    readonly_fields = ["object_str"]
    raw_id_fields = ["content_type"]


@admin.register(MissiveRelatedObject)
class MissiveRelatedObjectAdmin(AdminBoostModel):
    """Admin for missive related object model."""

    list_display = [
        "id",
        "missive",
        "content_type",
        "object_id",
        "content_object_display",
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
        "object_str",
        "created_at",
    ]
    raw_id_fields = ["missive", "content_type"]

    @admin.display(description=_("Related Object"))
    def content_object_display(self, obj):
        """Display the related object or its saved string representation."""
        if obj.content_object:
            return str(obj.content_object)
        elif obj.object_str:
            return f"{obj.object_str} (deleted)"
        return f"{obj.content_type} #{obj.object_id}"

    def change_fieldsets(self):
        """Configure fieldsets for change view."""
        self.add_to_fieldset(
            None,
            ["missive", "content_type", "object_id", "content_object", "object_str"],
        )
        self.add_to_fieldset(
            _("Timestamps"),
            ["created_at"],
        )
